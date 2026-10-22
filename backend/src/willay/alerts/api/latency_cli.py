"""Latency report: `make latency ARGS="--minutes 60"`.

p50, p95 and max of reading received → first alert sent, over the incidents opened in a
period. Exits with 1 when p95 misses SPEC's target (< 30 s), so a load test can fail on it.
"""

import argparse
import asyncio
import sys
from datetime import datetime, timedelta

from willay.alerts.domain.latency import TARGET_P95_S, summarize
from willay.alerts.infrastructure.sql_latency import received_to_alert_seconds
from willay.shared.clock import SystemClock
from willay.shared.config import get_settings
from willay.shared.db import create_engine


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--since", type=datetime.fromisoformat, help="start, ISO 8601 with offset (inclusive)"
    )
    parser.add_argument(
        "--until", type=datetime.fromisoformat, help="end, ISO 8601 with offset (exclusive)"
    )
    parser.add_argument(
        "--minutes", type=int, default=60, help="without --since: the last N minutes (60)"
    )
    return parser.parse_args(argv)


async def _report(since: datetime, until: datetime) -> int:
    engine = create_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            summary = summarize(await received_to_alert_seconds(conn, since, until))
    finally:
        await engine.dispose()
    print(f"Incidents opened by a reading from {since.isoformat()} to {until.isoformat()}")
    if summary is None:
        print("None of them sent an alert in this period: nothing to measure.")
        return 0
    verdict = "meets" if summary.meets_target else "MISSES"
    print(f"  incidents with an alert sent: {summary.count}")
    print(f"  p50: {summary.p50:.3f} s")
    print(f"  p95: {summary.p95:.3f} s ({verdict} the target < {TARGET_P95_S:.0f} s)")
    print(f"  max: {summary.max:.3f} s")
    return 0 if summary.meets_target else 1


def main(argv: list[str] | None = None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    until = args.until or SystemClock().now()
    since = args.since or until - timedelta(minutes=args.minutes)
    return asyncio.run(_report(since, until))


if __name__ == "__main__":
    sys.exit(main())
