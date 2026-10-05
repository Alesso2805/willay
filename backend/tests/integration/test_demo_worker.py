"""VIG-43: the public demo worker against real Postgres, with a FakeClock: the stations report
every 10 s, a scenario plays the Rímac story from a clean slate, and the nightly restore puts
the seed back."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.api import ensure_seed
from tests.integration.conftest import Database
from tests.integration.factories import FAST_HASHER
from willay.demo import live, reset
from willay.demo.runs import RunKind, SqlDemoRuns
from willay.seed import data
from willay.shared.clock import FakeClock
from willay.shared.db import create_engine
from willay.workers.demo import DemoWorker

pytestmark = pytest.mark.integration

RIMAC = data.RIMAC.id
CODES = sorted(s.code for s in data.STATIONS if s.organization_id == RIMAC)
T = datetime(2026, 10, 5, 15, 0, 3, tzinfo=UTC)  # 10:00:03 in Lima, far from the nightly 04:00


@pytest.fixture
async def engines(database: Database) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    await ensure_seed(database)
    app, owner = create_engine(database.app_url), create_engine(database.migrate_url)
    await _clean(owner)
    yield app, owner
    await _clean(owner)
    await app.dispose()
    await owner.dispose()


async def _clean(owner: AsyncEngine) -> None:
    async with owner.begin() as conn:
        await reset.clear(conn, RIMAC)
        await conn.exec_driver_sql("DELETE FROM core.demo_runs")


def _worker(engines: tuple[AsyncEngine, AsyncEngine], clock: FakeClock) -> DemoWorker:
    app, owner = engines
    return DemoWorker(app, owner, clock, RIMAC, restore_hour=4, hasher=FAST_HASHER)


async def _readings(conn: asyncpg.Connection) -> dict[datetime, dict[str, float]]:
    rows = await conn.fetch(
        "SELECT r.measured_at, s.code, r.value FROM ingest.readings r"
        " JOIN core.stations s ON s.id = r.station_id WHERE s.organization_id = $1",
        RIMAC,
    )
    by_time: dict[datetime, dict[str, float]] = {}
    for row in rows:
        by_time.setdefault(row["measured_at"], {})[row["code"]] = row["value"]
    return by_time


async def _request(app: AsyncEngine, now: datetime) -> int:
    async with app.begin() as conn:
        run = await SqlDemoRuns(conn).request(RIMAC, RunKind.SCENARIO, None, now)
    assert run is not None
    return run.id


async def _run(owner: asyncpg.Connection, run_id: int) -> asyncpg.Record:
    row = await owner.fetchrow("SELECT * FROM core.demo_runs WHERE id = $1", run_id)
    assert row is not None
    return row


async def test_every_station_reports_every_10_s_without_a_run(
    engines: tuple[AsyncEngine, AsyncEngine], owner: asyncpg.Connection
) -> None:
    clock = FakeClock(T)
    worker = _worker(engines, clock)
    await worker.tick()
    clock.advance(timedelta(seconds=4))
    await worker.tick()  # the same 10 s step: nothing new
    clock.advance(timedelta(seconds=4))
    await worker.tick()  # 15:00:11, the next step

    readings = await _readings(owner)
    first = live.normal_time(live.normal_step(T))
    assert sorted(readings) == [first, first + timedelta(seconds=10)]
    assert sorted(readings[first]) == CODES
    queued = await owner.fetchval(
        "SELECT count(*) FROM ingest.evaluation_queue WHERE organization_id = $1", RIMAC
    )
    assert queued == 2 * len(CODES)  # enqueued for the evaluator, like POST /v1/readings


async def test_a_scenario_plays_the_rimac_story_from_a_clean_slate(
    engines: tuple[AsyncEngine, AsyncEngine], owner: asyncpg.Connection
) -> None:
    app, _ = engines
    clock = FakeClock(T)
    worker = _worker(engines, clock)
    await worker.tick()  # the usual readings, which the run will clear
    run_id = await _request(app, T)

    clock.advance(timedelta(seconds=1))
    await worker.tick()
    start = (await _run(owner, run_id))["started_at"]
    assert start == T + timedelta(seconds=1)
    assert sorted(await _readings(owner)) == [start]  # the earlier ones are gone

    clock.set(start + timedelta(seconds=60))
    await worker.tick()
    drop = (await _readings(owner))[start + timedelta(seconds=60)]
    assert drop["RIM-CHA-01"] == pytest.approx(34, rel=0.1)  # the downstream discharge fell

    clock.set(start + timedelta(seconds=300))
    await worker.tick()
    silence = (await _readings(owner))[start + timedelta(seconds=300)]
    assert "RIM-SEU-01" not in silence  # the upstream station stopped reporting
    assert "RIM-CHA-01" in silence

    clock.set(start + timedelta(seconds=541))
    await worker.tick()
    run = await _run(owner, run_id)
    assert (run["outcome"], run["finished_at"]) == ("done", start + timedelta(seconds=541))
    back = (await _readings(owner))[live.normal_time(live.normal_step(clock.now()))]
    assert sorted(back) == CODES  # the river as usual, upstream station included


async def test_a_scenario_without_its_stations_ends_failed_with_the_reason(
    engines: tuple[AsyncEngine, AsyncEngine], owner: asyncpg.Connection
) -> None:
    app, _ = engines
    await owner.execute("UPDATE core.stations SET status = 'inactive' WHERE code = 'RIM-SEU-01'")
    try:
        run_id = await _request(app, T)
        await _worker(engines, FakeClock(T)).tick()
        run = await _run(owner, run_id)
    finally:
        await owner.execute("UPDATE core.stations SET status = 'active' WHERE code = 'RIM-SEU-01'")
    assert run["outcome"] == "failed"
    assert "RIM-SEU-01" in run["error"]


async def test_the_nightly_restore_puts_the_seed_back(
    engines: tuple[AsyncEngine, AsyncEngine], owner: asyncpg.Connection
) -> None:
    zone = data.ZONES[0]
    other_zone = next(z for z in data.ZONES if z.organization_id != RIMAC)
    # What a day of visitors leaves behind.
    await owner.execute("UPDATE core.risk_zones SET name = 'Renombrada' WHERE id = $1", zone.id)
    await owner.execute("UPDATE core.organizations SET language = 'en' WHERE id = $1", RIMAC)
    await owner.execute(
        "INSERT INTO core.risk_zones (id, organization_id, name, risk_level, geom)"
        " SELECT gen_random_uuid(), organization_id, 'De un visitante', risk_level, geom"
        " FROM core.risk_zones WHERE id = $1",
        zone.id,
    )
    await owner.execute(
        "INSERT INTO core.audit_log (organization_id, entity_type, entity_id, action, at)"
        " VALUES ($1, 'zone', $2, 'update', now())",
        RIMAC,
        zone.id,
    )
    other_before = await owner.fetchval(
        "SELECT name FROM core.risk_zones WHERE id = $1", other_zone.id
    )

    # 03:59:55 in Lima: five seconds before the restore.
    clock = FakeClock(datetime(2026, 10, 5, 8, 59, 55, tzinfo=UTC))
    worker = _worker(engines, clock)
    await worker.tick()
    assert await owner.fetchval("SELECT count(*) FROM core.demo_runs") == 0
    clock.advance(timedelta(seconds=6))
    await worker.tick()

    restored = await owner.fetchrow("SELECT * FROM core.demo_runs WHERE kind = 'restore'")
    assert restored is not None
    assert restored["outcome"] == "done"
    names = await owner.fetch("SELECT name FROM core.risk_zones WHERE organization_id = $1", RIMAC)
    assert sorted(r["name"] for r in names) == sorted(
        z.name for z in data.ZONES if z.organization_id == RIMAC
    )
    language = await owner.fetchval("SELECT language FROM core.organizations WHERE id = $1", RIMAC)
    assert language == "es"
    audited = await owner.fetchval(
        "SELECT count(*) FROM core.audit_log WHERE organization_id = $1", RIMAC
    )
    assert audited == 0
    # Only the demo organization: another one keeps what it had.
    assert (
        await owner.fetchval("SELECT name FROM core.risk_zones WHERE id = $1", other_zone.id)
        == other_before
    )

    clock.advance(timedelta(hours=1))
    await worker.tick()  # tomorrow's comes tomorrow
    assert await owner.fetchval("SELECT count(*) FROM core.demo_runs") == 1
