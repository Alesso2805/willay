"""Station simulator CLI (VIG-11): `simulate` or `make simulate ARGS="..."`.

Examples:
    simulate --scenario normal --stations 3 --seed 7 --steps 12
    simulate --scenario rimac --seed 42          # SPEC demo; Ctrl+C to stop

Sends real readings to POST /v1/readings with the API keys `make seed` saved in
.secrets/station-keys.json. A dev/demo tool: each station's variable comes from the seed data.
"""

import argparse
import asyncio
import json
import math
import sys
from pathlib import Path

import httpx2

from willay.ingestion.application.simulate import SimulatedStation, TickReport, run_simulation
from willay.ingestion.domain.simulation import (
    Behavior,
    MissingStationsError,
    Scenario,
    build_plan,
)
from willay.ingestion.infrastructure.http_sender import HttpReadingSender
from willay.seed import data as seed_data
from willay.shared.clock import SystemClock

_VARIABLES = {station.code: station.variable for station in seed_data.STATIONS}


def load_stations(keys_file: Path, organization: str, limit: int | None) -> list[tuple[str, str]]:
    """(code, api_key) pairs of the organization, sorted by code."""
    keys = json.loads(keys_file.read_text(encoding="utf-8"))
    stations = sorted(
        (code, entry["api_key"])
        for code, entry in keys.items()
        if entry.get("organization") == organization
    )
    return stations[:limit] if limit else stations


def _format_tick(report: TickReport) -> str:
    values = " ".join(
        f"{code}={'—' if value is None else value}" for code, value in report.values.items()
    )
    problems = {code: status for code, status in report.statuses.items() if status != 202}
    suffix = f"  failed: {problems}" if problems else ""
    return f"[{report.step:>4}] {report.at:%H:%M:%S} {values}{suffix}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="simulate", description=__doc__.split("\n\n")[0])
    parser.add_argument("--scenario", type=Scenario, choices=list(Scenario), required=True)
    parser.add_argument("--seed", type=int, required=True, help="same seed, same series")
    parser.add_argument("--stations", type=int, help="use only the first N (by code)")
    parser.add_argument("--org", default="rimac", help="organization alias (rimac)")
    parser.add_argument("--interval", type=float, default=10.0, help="seconds between batches")
    parser.add_argument(
        "--event-after", type=float, default=60.0, help="seconds until the rise/drop/silence"
    )
    parser.add_argument("--steps", type=int, help="number of steps (default: endless)")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--keys-file", type=Path, default=Path(".secrets/station-keys.json"))
    return parser


async def _run(args: argparse.Namespace) -> None:
    keys = load_stations(args.keys_file, args.org, args.stations)
    if not keys:
        sys.exit(f"No keys for organization '{args.org}' in {args.keys_file}")
    try:
        plan = build_plan(
            args.scenario,
            [(code, _VARIABLES.get(code, "discharge")) for code, _ in keys],
            event_step=math.ceil(args.event_after / args.interval),
            interval_s=args.interval,
        )
    except MissingStationsError as exc:
        sys.exit(str(exc))

    api_keys = dict(keys)
    stations = [SimulatedStation(p, api_keys[p.code]) for p in plan]
    for p in plan:
        when = "" if p.behavior is Behavior.NORMAL else f" from step {p.event_step}"
        print(f"  {p.code:<11} {p.variable:<12} {p.behavior}{when}")
    async with httpx2.AsyncClient(base_url=args.api_url, timeout=10.0) as client:
        await run_simulation(
            stations,
            seed=args.seed,
            interval_s=args.interval,
            steps=args.steps,
            clock=SystemClock(),
            sleep=asyncio.sleep,
            sender=HttpReadingSender(client),
            on_tick=lambda report: print(_format_tick(report), flush=True),
        )


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if not args.keys_file.exists():
        sys.exit(f"{args.keys_file} does not exist: run `make seed` first")
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\nSimulation stopped.")


if __name__ == "__main__":
    main()
