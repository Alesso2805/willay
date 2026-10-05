"""Public demo worker (VIG-43): `python -m willay.workers.demo`.

Disabled (heartbeat only) unless WILLAY_DEMO_MODE is set. Every 2 s it:
1. asks for a restore run when the demo organization's nightly hour comes;
2. plays the organization's unfinished run:
   - a restore puts it back as the seed made it, in one go;
   - a scenario starts from a clean slate and ends after the Rímac story;
3. sends the readings that are due: the scenario's while one plays, the normal river otherwise.

Readings go through the same use case as POST /v1/readings (`ingest_batch`), so they are
stored, enqueued and notified to the evaluator in one transaction. They carry no API key: this
process is the stations' simulator. Clearing and restoring connect as willay_owner, because
incident events are append-only for willay_app.
"""

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from willay.demo import live, reset
from willay.demo.restore import restore
from willay.demo.runs import DemoRun, Outcome, RunKind, SqlDemoRuns, demo_organization
from willay.ingestion.application.authenticate_station import AuthenticatedStation
from willay.ingestion.application.ingest_batch import ingest_batch
from willay.ingestion.domain.readings import Reading
from willay.ingestion.domain.simulation import MissingStationsError, StationPlan
from willay.ingestion.infrastructure.api_keys import ApiKeyHasher
from willay.ingestion.infrastructure.repositories import SqlReadingWriter
from willay.shared.clock import Clock, SystemClock
from willay.shared.config import Settings
from willay.shared.db import create_engine
from willay.workers._runner import run_async_worker, run_loop

TICK_S = 2.0
log = structlog.get_logger()

_STATIONS = text("""
    SELECT id, code, variable FROM core.stations
    WHERE organization_id = :organization_id AND status = 'active'
    ORDER BY code
""")
_TIMEZONE = text("SELECT timezone FROM core.organizations WHERE id = :organization_id")


@dataclass(frozen=True)
class DemoStation:
    id: UUID
    code: str
    variable: str


class DemoWorker:
    def __init__(
        self,
        app: AsyncEngine,
        owner: AsyncEngine,
        clock: Clock,
        organization_id: UUID,
        *,
        restore_hour: int,
        hasher: ApiKeyHasher,
    ) -> None:
        self._app = app
        self._owner = owner
        self._clock = clock
        self._organization_id = organization_id
        self._restore_hour = restore_hour
        self._hasher = hasher
        # Before the first restore, the nightly hour counts from when the worker started.
        self._since = clock.now()
        # The last step sent: (run id or None outside a run, step). Not repeated within a run.
        self._sent: tuple[int | None, int] | None = None

    async def tick(self) -> bool:
        now = self._clock.now()
        await self._schedule_restore(now)
        run = await self._play(now)
        await self._send_readings(run, now)
        return False

    async def _schedule_restore(self, now: datetime) -> None:
        async with self._app.begin() as conn:
            runs = SqlDemoRuns(conn)
            timezone: str = await conn.scalar(_TIMEZONE, {"organization_id": self._organization_id})
            last = await runs.last_restore(self._organization_id) or self._since
            if now >= live.next_restore(last, timezone, self._restore_hour):
                # While a scenario plays the insert does nothing: the restore waits for it.
                await runs.request(self._organization_id, RunKind.RESTORE, None, now)

    async def _play(self, now: datetime) -> DemoRun | None:
        """The scenario playing now, if any, after starting or finishing what is due."""
        async with self._app.begin() as conn:
            run = await SqlDemoRuns(conn).active(self._organization_id)
        if run is None:
            return None
        if run.kind is RunKind.RESTORE:
            await self._restore(run, now)
            return None
        if run.started_at is None:
            return await self._start_scenario(run, now)
        if live.scenario_step(run.started_at, now) >= live.END_STEP:
            await self._finish(run, now, Outcome.DONE)
            return None
        try:  # a visitor may have deactivated one of the story's stations meanwhile
            live.scenario_plans([(s.code, s.variable) for s in await self._stations()])
        except MissingStationsError as exc:
            await self._finish(run, now, Outcome.FAILED, str(exc))
            return None
        return run

    async def _restore(self, run: DemoRun, now: datetime) -> None:
        log.info("demo_restore_started", run_id=run.id)
        try:
            async with self._owner.begin() as conn:
                await SqlDemoRuns(conn).start(run.id, now)
                await restore(conn, self._organization_id, self._clock, self._hasher)
        except Exception as exc:
            log.exception("demo_restore_failed", run_id=run.id)
            await self._finish(run, self._clock.now(), Outcome.FAILED, str(exc))
            return
        await self._finish(run, self._clock.now(), Outcome.DONE)
        self._sent = None

    async def _start_scenario(self, run: DemoRun, now: datetime) -> DemoRun | None:
        stations = await self._stations()
        try:
            live.scenario_plans([(s.code, s.variable) for s in stations])
        except MissingStationsError as exc:
            await self._finish(run, now, Outcome.FAILED, str(exc))
            return None
        async with self._owner.begin() as conn:
            # A clean slate: an earlier incident would swallow this run's or hold it back
            # with its cooldown (see willay.demo.reset).
            await reset.clear(conn, self._organization_id)
            await SqlDemoRuns(conn).start(run.id, now)
        log.info("demo_scenario_started", run_id=run.id)
        return replace(run, started_at=now)

    async def _finish(
        self, run: DemoRun, now: datetime, outcome: Outcome, error: str | None = None
    ) -> None:
        async with self._app.begin() as conn:
            await SqlDemoRuns(conn).finish(run.id, now, outcome, error)
        log.info("demo_run_finished", run_id=run.id, kind=run.kind, outcome=outcome, error=error)

    async def _send_readings(self, run: DemoRun | None, now: datetime) -> None:
        stations = await self._stations()
        pairs = [(s.code, s.variable) for s in stations]
        if run is not None and run.started_at is not None:
            step = live.scenario_step(run.started_at, now)
            key: tuple[int | None, int] = (run.id, step)
            plans: list[StationPlan] = live.scenario_plans(pairs)
            measured_at = live.scenario_time(run.started_at, step)
        else:
            step = live.normal_step(now)
            key = (None, step)
            plans = live.normal_plans(pairs)
            measured_at = live.normal_time(step)
        if key == self._sent:
            return
        values = live.values(plans, step)
        async with self._app.begin() as conn:
            writer = SqlReadingWriter(conn)
            for station in stations:
                value = values.get(station.code)
                if value is None:  # silent in the story
                    continue
                identity = AuthenticatedStation(station.id, self._organization_id)
                await ingest_batch(identity, [Reading(measured_at, value)], self._clock, writer)
        self._sent = key

    async def _stations(self) -> list[DemoStation]:
        async with self._app.connect() as conn:
            rows = await conn.execute(_STATIONS, {"organization_id": self._organization_id})
            return [DemoStation(r.id, r.code, r.variable) for r in rows]


async def run_demo(settings: Settings, stop: asyncio.Event) -> None:
    heartbeat = settings.heartbeat_dir / "demo.alive"
    organization_id = demo_organization(settings)
    if organization_id is None or settings.migrate_database_url is None:
        log.warning("demo_disabled", reason="WILLAY_DEMO_MODE or WILLAY_MIGRATE_DATABASE_URL")
        await run_loop("demo", 10.0, heartbeat, stop)
        return
    app = create_engine(settings.database_url)
    owner = create_engine(settings.migrate_database_url)
    try:
        worker = DemoWorker(
            app,
            owner,
            SystemClock(),
            organization_id,
            restore_hour=settings.demo_restore_hour,
            hasher=ApiKeyHasher(),
        )
        await run_loop("demo", TICK_S, heartbeat, stop, worker.tick)
    finally:
        await app.dispose()
        await owner.dispose()


def main() -> None:
    run_async_worker("demo", run_demo)


if __name__ == "__main__":
    main()
