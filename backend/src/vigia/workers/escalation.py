"""Worker escalation (VIG-24): `python -m vigia.workers.escalation`.

Cada 15 s sube de nivel los incidentes abiertos cuyo nivel venció sin confirmación, y
registra cuándo se agota la política. Las alertas del nivel nuevo las envía el dispatcher,
que despierta con el NOTIFY que emite el planificador de alertas.
"""

import asyncio

from vigia.alerts.application.escalation import Escalator
from vigia.alerts.application.planning import AlertPlanner
from vigia.alerts.infrastructure.sql_alerts import SqlAlertRepository
from vigia.alerts.infrastructure.sql_escalation import SqlEscalationRepository
from vigia.shared.clock import Clock, SystemClock
from vigia.shared.config import Settings
from vigia.shared.db import create_engine
from vigia.workers._runner import run_async_worker, run_loop

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
