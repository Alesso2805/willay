"""`make loadtest ARGS="--minutes 30"`.

Prepares the "Carga" organization, sends one reading per station every interval to the API for
the given minutes, waits until every reading should be evaluated and checks SPEC: every batch
accepted, no `ok` reading left unevaluated after 120 s, and p95 of reading received → first
alert sent under 30 s. Exits with 1 if any of them fails.

It runs in the migrate container (`docker compose run`), which reaches both the database and
the API (`http://api:8000`) over the compose network.
"""

import argparse
import asyncio
import sys
import time
from datetime import datetime, timedelta

import httpx2

from willay.alerts.domain.latency import TARGET_P95_S, summarize
from willay.alerts.infrastructure.sql_latency import received_to_alert_seconds
from willay.ingestion.infrastructure.api_keys import ApiKeyHasher
from willay.ingestion.infrastructure.http_sender import HttpReadingSender
from willay.loadtest import checks, setup
from willay.loadtest.plan import SETTLE_S, LoadPlan, Outcome, build_plan
from willay.shared.clock import SystemClock
from willay.shared.config import get_settings
from willay.shared.db import create_engine


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m willay.loadtest", description=__doc__)
    parser.add_argument("--minutes", type=float, default=30, help="how long it sends (30)")
    parser.add_argument("--stations", type=int, default=50, help="how many stations (50)")
    parser.add_argument("--interval", type=float, default=10, help="seconds between rounds (10)")
    parser.add_argument("--seed", type=int, default=29, help="spike schedule; same seed, same run")
    parser.add_argument("--api-url", default="http://api:8000", help="the API to load")
    return parser.parse_args(argv)


async def _send(plan: LoadPlan, stations: list[setup.LoadStation], api_url: str) -> tuple[int, int]:
    """Every station, every round, concurrently; rounds keep the interval. (sent, rejected)."""
    clock = SystemClock()
    sent = rejected = 0
    async with httpx2.AsyncClient(base_url=api_url, timeout=10) as client:
        sender = HttpReadingSender(client)
        start = time.monotonic()
        for tick in range(plan.ticks):
            measured_at = clock.now()
            statuses = await asyncio.gather(
                *(
                    sender.send(station.api_key, measured_at, plan.value(index, tick))
                    for index, station in enumerate(stations)
                )
            )
            sent += len(statuses)
            rejected += sum(1 for status in statuses if status != 202)
            if (tick + 1) % max(1, int(60 / plan.interval_s)) == 0:
                print(
                    f"  {tick + 1}/{plan.ticks} rounds, {sent} batches, {rejected} rejected",
                    flush=True,
                )
            await asyncio.sleep(max(0.0, start + (tick + 1) * plan.interval_s - time.monotonic()))
    return sent, rejected


async def _run(args: argparse.Namespace) -> int:
    plan = build_plan(args.stations, args.minutes, args.interval, args.seed)
    engine = create_engine(get_settings().database_url)
    try:
        async with httpx2.AsyncClient(timeout=5) as client:
            try:
                (await client.get(f"{args.api_url}/health")).raise_for_status()
            except httpx2.HTTPError:
                print(f"The API does not answer at {args.api_url}: start the stack (make up).")
                return 1
        since = SystemClock().now()
        async with engine.begin() as conn:
            stations = await setup.prepare(conn, plan.stations, since, ApiKeyHasher())
        print(
            f"Load test: {plan.stations} stations x 1 reading every {plan.interval_s:g} s "
            f"for {args.minutes:g} min ({plan.ticks} rounds), one spike per station",
            flush=True,  # without a terminal (CI, a log file) output is buffered until the end
        )
        sent, rejected = await _send(plan, stations, args.api_url)
        print(f"Sent. Waiting {SETTLE_S} s for every reading to be evaluated…", flush=True)
        await asyncio.sleep(SETTLE_S)
        until = SystemClock().now()
        async with engine.connect() as conn:
            outcome = Outcome(
                sent=sent,
                rejected=rejected,
                unevaluated=await checks.unevaluated(conn, setup.ORGANIZATION, since),
                latencies=await received_to_alert_seconds(
                    conn, since, until + timedelta(seconds=1), setup.ORGANIZATION
                ),
            )
            stored = await checks.stored(conn, setup.ORGANIZATION, since)
    finally:
        await engine.dispose()
    return _report(outcome, stored, since)


def _report(outcome: Outcome, stored: int, since: datetime) -> int:
    summary = summarize(outcome.latencies)
    print(f"\nResults since {since.isoformat()}")
    print(f"  batches sent: {outcome.sent}, rejected: {outcome.rejected}")
    print(
        f"  readings stored: {stored}, left unevaluated after {SETTLE_S} s: {outcome.unevaluated}"
    )
    if summary is not None:
        print(f"  incidents measured: {summary.count}")
        print(f"  received -> first alert: p50 {summary.p50:.3f} s, p95 {summary.p95:.3f} s, "
              f"max {summary.max:.3f} s (target p95 < {TARGET_P95_S:.0f} s)")  # fmt: skip
    problems = outcome.problems()
    for problem in problems:
        print(f"  FAIL: {problem}")
    print("  PASS" if not problems else "")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(_parse(sys.argv[1:] if argv is None else argv)))


if __name__ == "__main__":
    sys.exit(main())
