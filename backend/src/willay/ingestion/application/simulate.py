"""Use case: run a simulation, sending one batch per station on every step.

Runs in real time on purpose: silence detection and escalation use the real clock, so speeding
up the simulator would not speed up the demo. Clock, sleep and sender are injected for tests.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from willay.ingestion.domain.simulation import StationPlan, value_at
from willay.shared.clock import Clock

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class SimulatedStation:
    plan: StationPlan
    api_key: str


class ReadingSender(Protocol):
    async def send(self, api_key: str, measured_at: datetime, value: float) -> int:
        """Send a one-reading batch. Returns the HTTP status (0 if there was no response)."""
        ...


@dataclass(frozen=True)
class TickReport:
    step: int
    at: datetime
    values: dict[str, float | None]  # None = the station is silent this step
    statuses: dict[str, int]  # HTTP status per station that sent


async def run_simulation(
    stations: list[SimulatedStation],
    *,
    seed: int,
    interval_s: float,
    steps: int | None,
    clock: Clock,
    sleep: Sleep,
    sender: ReadingSender,
    on_tick: Callable[[TickReport], None],
) -> None:
    start = clock.now()
    step = 0
    while steps is None or step < steps:
        # Scheduled from the start, not from the previous step, so send time does not
        # accumulate and the station keeps its expected interval.
        wait = (start + timedelta(seconds=interval_s * step) - clock.now()).total_seconds()
        if wait > 0:
            await sleep(wait)
        now = clock.now()

        values = {s.plan.code: value_at(s.plan, seed, step) for s in stations}
        batches = [(s, v) for s in stations if (v := values[s.plan.code]) is not None]
        codes = await asyncio.gather(*(sender.send(s.api_key, now, v) for s, v in batches))
        statuses = {s.plan.code: code for (s, _), code in zip(batches, codes, strict=True)}
        on_tick(TickReport(step, now, values, statuses))
        step += 1
