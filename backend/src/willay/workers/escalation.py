"""Escalation worker (VIG-24): `python -m willay.workers.escalation`.

Every 15 s it moves open incidents whose level expired unacknowledged to the next level and
records when the policy is exhausted. The dispatcher sends the new level's alerts, woken by
the NOTIFY the alert planner emits.
"""

import asyncio

from willay.alerts.application.escalation import Escalator
from willay.alerts.application.planning import AlertPlanner
from willay.alerts.infrastructure.sql_alerts import SqlAlertRepository
from willay.alerts.infrastructure.sql_escalation import SqlEscalationRepository
from willay.shared.clock import Clock, SystemClock
from willay.shared.config import Settings
from willay.shared.db import create_engine
from willay.workers._runner import run_async_worker, run_loop

NAME = "escalation"
INTERVAL_S = 15.0


async def run_escalation(
    settings: Settings,
    stop: asyncio.Event,
    *,
    clock: Clock | None = None,
    interval_s: float = INTERVAL_S,
) -> None:
    clock = clock or SystemClock()
    engine = create_engine(settings.database_url)
    escalator = Escalator(
        SqlEscalationRepository(), AlertPlanner(SqlAlertRepository()), clock, engine.begin
    )

    async def tick() -> None:
        await escalator.run()

    try:
        heartbeat = settings.heartbeat_dir / f"{NAME}.alive"
        await run_loop(NAME, interval_s, heartbeat, stop, tick)
    finally:
        await engine.dispose()


def main() -> None:
    run_async_worker(NAME, run_escalation)


if __name__ == "__main__":
    main()
