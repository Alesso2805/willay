"""Worker silence (VIG-17): `python -m vigia.workers.silence`.

Cada 15 s busca estaciones que dejaron de reportar y abre un incidente por estación. Con
ese ciclo, el incidente llega antes de K * intervalo + 30 s desde el último latido
(SPEC): como mucho K * intervalo más un ciclo. En el mismo ciclo anota station_recovered
en las estaciones que volvieron y purga las ventanas de rate limit de más de una hora.
"""

import asyncio

from vigia.alerts.application.planning import AlertPlanner
from vigia.alerts.infrastructure.sql_alerts import SqlAlertRepository
from vigia.incidents.infrastructure.sql_incidents import SqlIncidentStore
from vigia.ingestion.domain.rate_limit import WINDOW_RETENTION
from vigia.ingestion.infrastructure.repositories import SqlBatchCounter
from vigia.rules.application.silence_check import SilenceChecker
from vigia.rules.infrastructure.sql_silence import SqlSilenceRepository
from vigia.shared.clock import Clock, SystemClock
from vigia.shared.config import Settings
from vigia.shared.db import create_engine
from vigia.workers._runner import run_async_worker, run_loop

NAME = "silence"
INTERVAL_S = 15.0


async def run_silence(
    settings: Settings,
    stop: asyncio.Event,
    *,
    clock: Clock | None = None,
    interval_s: float = INTERVAL_S,
) -> None:
    clock = clock or SystemClock()
    engine = create_engine(settings.database_url)
    checker = SilenceChecker(
        SqlSilenceRepository(),
        SqlIncidentStore(),
        clock,
        engine.begin,
        alerts=AlertPlanner(SqlAlertRepository()),
    )
    rate_limits = SqlBatchCounter(engine)

    async def tick() -> None:
        await checker.run()
        await rate_limits.purge(clock.now() - WINDOW_RETENTION)

    try:
        heartbeat = settings.heartbeat_dir / f"{NAME}.alive"
        await run_loop(NAME, interval_s, heartbeat, stop, tick)
    finally:
        await engine.dispose()


def main() -> None:
    run_async_worker(NAME, run_silence)


if __name__ == "__main__":
    main()
