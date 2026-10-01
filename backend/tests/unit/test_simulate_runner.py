import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from vigia.ingestion.api.simulator_cli import load_stations
from vigia.ingestion.application.simulate import (
    SimulatedStation,
    Sleep,
    TickReport,
    run_simulation,
)
from vigia.ingestion.domain.simulation import (
    RIMAC_DOWNSTREAM,
    RIMAC_UPSTREAM,
    Scenario,
    build_plan,
    value_at,
)
from vigia.shared.clock import FakeClock

T0 = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


class FakeSender:
    def __init__(self, clock: FakeClock, latency: timedelta = timedelta(0)) -> None:
        self.clock = clock
        self.latency = latency
        self.sent: list[tuple[str, datetime, float]] = []

    async def send(self, api_key: str, measured_at: datetime, value: float) -> int:
        self.sent.append((api_key, measured_at, value))
        self.clock.advance(self.latency)  # simulates the request's latency
        return 202


def _sleeper(clock: FakeClock) -> Sleep:
    async def sleep(seconds: float) -> None:
        clock.advance(timedelta(seconds=seconds))

    return sleep


async def _run(
    stations: list[SimulatedStation], clock: FakeClock, sender: FakeSender, steps: int
) -> list[TickReport]:
    reports: list[TickReport] = []
    await run_simulation(
        stations,
        seed=42,
        interval_s=10,
        steps=steps,
        clock=clock,
        sleep=_sleeper(clock),
        sender=sender,
        on_tick=reports.append,
    )
    return reports


async def test_rimac_demo_runs_in_simulated_time() -> None:
    plan = build_plan(
        Scenario.RIMAC,
        [(RIMAC_DOWNSTREAM, "discharge"), (RIMAC_UPSTREAM, "discharge")],
        event_step=6,
        interval_s=10,
    )
    stations = [SimulatedStation(p, f"key-{p.code}") for p in plan]
    clock = FakeClock(T0)
    sender = FakeSender(clock)

    reports = await _run(stations, clock, sender, steps=40)  # 6 min 40 s of demo time in ms

    upstream = [m for key, m, _ in sender.sent if key == f"key-{RIMAC_UPSTREAM}"]
    downstream = [(m, v) for key, m, v in sender.sent if key == f"key-{RIMAC_DOWNSTREAM}"]
    assert len(downstream) == 40
    # Upstream goes silent at step 30 (1 min + 4 min): its last batch is step 29's.
    assert len(upstream) == 30
    assert upstream[-1] == T0 + timedelta(seconds=290)
    assert reports[30].values[RIMAC_UPSTREAM] is None
    assert RIMAC_UPSTREAM not in reports[30].statuses
    # What was sent is exactly the domain series for that seed.
    plan_down = next(p for p in plan if p.code == RIMAC_DOWNSTREAM)
    assert [v for _, v in downstream] == [value_at(plan_down, 42, s) for s in range(40)]


async def test_schedule_does_not_drift_with_slow_requests() -> None:
    plan = build_plan(Scenario.NORMAL, [("A", "discharge")], event_step=0, interval_s=10)
    clock = FakeClock(T0)
    sender = FakeSender(clock, latency=timedelta(seconds=3))

    await _run([SimulatedStation(plan[0], "k")], clock, sender, steps=4)

    # Scheduled against the start: each send's 3 s do not pile up (not 0, 13, 26, 39).
    assert [m for _, m, _ in sender.sent] == [T0 + timedelta(seconds=s) for s in (0, 10, 20, 30)]


def test_load_stations_filters_by_organization_sorts_and_limits(tmp_path: Path) -> None:
    keys = tmp_path / "keys.json"
    keys.write_text(
        json.dumps(
            {
                "RIM-SEU-01": {"organization": "rimac", "api_key": "k-seu"},
                "AIS-01": {"organization": "aislamiento", "api_key": "k-ais"},
                "RIM-CHA-01": {"organization": "rimac", "api_key": "k-cha"},
                "RIM-HUA-01": {"organization": "rimac", "api_key": "k-hua"},
            }
        )
    )
    assert load_stations(keys, "rimac", None) == [
        ("RIM-CHA-01", "k-cha"),
        ("RIM-HUA-01", "k-hua"),
        ("RIM-SEU-01", "k-seu"),
    ]
    assert load_stations(keys, "rimac", 2) == [("RIM-CHA-01", "k-cha"), ("RIM-HUA-01", "k-hua")]
