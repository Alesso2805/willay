"""Silence worker: `python -m willay.workers.silence`.

Every 15 s it opens one incident per station that stopped reporting; with that cycle the
incident arrives within K * interval + 30 s of the last heartbeat (SPEC). The same cycle
records station_recovered for stations that came back and purges rate-limit and key-failure
windows older than one hour.
"""

import asyncio

from willay.alerts.application.planning import AlertPlanner
from willay.alerts.infrastructure.sql_alerts import SqlAlertRepository
from willay.incidents.infrastructure.sql_incidents import SqlIncidentStore
from willay.ingestion.domain.rate_limit import WINDOW_RETENTION
from willay.ingestion.infrastructure.repositories import SqlBatchCounter, SqlKeyFailureCounter
from willay.rules.application.silence_check import SilenceChecker
from willay.rules.infrastructure.sql_silence import SqlSilenceRepository
from willay.shared.clock import Clock, SystemClock
from willay.shared.config import Settings
from willay.shared.db import create_engine
from willay.workers._runner import run_async_worker, run_loop

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
    key_failures = SqlKeyFailureCounter(engine)

    async def tick() -> None:
        await checker.run()
        await rate_limits.purge(clock.now() - WINDOW_RETENTION)
        await key_failures.purge(clock.now() - WINDOW_RETENTION)

    try:
        heartbeat = settings.heartbeat_dir / f"{NAME}.alive"
        await run_loop(NAME, interval_s, heartbeat, stop, tick)
    finally:
        await engine.dispose()


def main() -> None:
    run_async_worker(NAME, run_silence)


if __name__ == "__main__":
    main()
