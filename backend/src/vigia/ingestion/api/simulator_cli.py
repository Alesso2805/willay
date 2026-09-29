"""CLI del simulador de estaciones (VIG-11): `simulate` o `make simulate ARGS="..."`.

Ejemplos:
    simulate --scenario normal --stations 3 --seed 7 --steps 12
    simulate --scenario rimac --seed 42          # demo de SPEC; Ctrl+C para detener

Envía lecturas reales a POST /v1/readings con las API keys que `make seed` guardó en
.secrets/station-keys.json. Es una herramienta de desarrollo y demo: toma la variable
de cada estación de los datos del seed.
"""

import argparse
import asyncio
import json
import math
import sys
from pathlib import Path

import httpx2

from vigia.ingestion.application.simulate import SimulatedStation, TickReport, run_simulation
from vigia.ingestion.domain.simulation import (
    Behavior,
    MissingStationsError,
    Scenario,
    build_plan,
)
from vigia.ingestion.infrastructure.http_sender import HttpReadingSender
from vigia.seed import data as seed_data
from vigia.shared.clock import SystemClock

_VARIABLES = {station.code: station.variable for station in seed_data.STATIONS}


def load_stations(keys_file: Path, organization: str, limit: int | None) -> list[tuple[str, str]]:
    """Pares (código, api_key) de la organización, ordenados por código."""
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
    suffix = f"  ¡{problems}!" if problems else ""
    return f"[{report.step:>4}] {report.at:%H:%M:%S} {values}{suffix}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="simulate", description=__doc__.split("\n\n")[0])
    parser.add_argument("--scenario", type=Scenario, choices=list(Scenario), required=True)
    parser.add_argument("--seed", type=int, required=True, help="misma semilla, misma serie")
    parser.add_argument("--stations", type=int, help="usar solo las N primeras (por código)")
    parser.add_argument("--org", default="rimac", help="alias de la organización (rimac)")
    parser.add_argument("--interval", type=float, default=10.0, help="segundos entre lotes")
    parser.add_argument(
        "--event-after", type=float, default=60.0, help="segundos hasta la subida/caída/silencio"
    )
    parser.add_argument("--steps", type=int, help="número de pasos (por defecto, sin fin)")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--keys-file", type=Path, default=Path(".secrets/station-keys.json"))
    return parser


async def _run(args: argparse.Namespace) -> None:
    keys = load_stations(args.keys_file, args.org, args.stations)
    if not keys:
        sys.exit(f"No hay claves de la organización '{args.org}' en {args.keys_file}")
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
        when = "" if p.behavior is Behavior.NORMAL else f" desde el paso {p.event_step}"
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
        sys.exit(f"No existe {args.keys_file}: ejecuta `make seed` primero")
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\nSimulación detenida.")


if __name__ == "__main__":
    main()
