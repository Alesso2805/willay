"""VIG-29: the load test's organization and checks against real Postgres. The full run (30 min
against the API) is a manual check: `make loadtest`."""

from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import Database
from tests.integration.factories import FAST_HASHER
from willay.ingestion.domain.readings import ClassifiedReading, Quality
from willay.ingestion.infrastructure.repositories import SqlReadingWriter
from willay.loadtest import checks, setup
from willay.shared.clock import SystemClock
from willay.shared.db import create_engine

pytestmark = pytest.mark.integration


@pytest.fixture
async def engine(database: Database) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


async def test_preparing_twice_keeps_the_stations_and_issues_new_keys(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    now = SystemClock().now()
    async with engine.begin() as conn:
        first = await setup.prepare(conn, 3, now, FAST_HASHER)
    async with engine.begin() as conn:
        second = await setup.prepare(conn, 3, now, FAST_HASHER)

    assert [s.code for s in first] == ["CAR-001", "CAR-002", "CAR-003"]
    assert [s.id for s in second] == [s.id for s in first]  # found again by their code
    assert {s.api_key for s in second}.isdisjoint({s.api_key for s in first})  # new keys
    rules = await owner.fetch(
        "SELECT station_id, params FROM core.rules WHERE organization_id = $1",
        setup.ORGANIZATION,
    )
    assert sorted(r["station_id"] for r in rules) == sorted(s.id for s in first)  # one each
    keys_match = [
        FAST_HASHER.verify(
            await owner.fetchval("SELECT api_key_hash FROM core.stations WHERE id = $1", s.id),
            s.api_key,
        )
        for s in second
    ]
    assert keys_match == [True, True, True]


async def test_preparing_resolves_what_a_previous_run_left_open(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    now = SystemClock().now()
    async with engine.begin() as conn:
        [station] = await setup.prepare(conn, 1, now, FAST_HASHER)
    rule_id = await owner.fetchval("SELECT id FROM core.rules WHERE station_id = $1", station.id)
    await owner.execute(
        "INSERT INTO core.incidents (id, organization_id, zone_id, rule_id, station_id, severity,"
        " dedup_key, opened_at, level_started_at) VALUES (gen_random_uuid(), $1, $2, $3, $4,"
        " 'warning', $5, $6, $6)",
        setup.ORGANIZATION, setup.ZONE, rule_id, station.id, f"{rule_id}:{setup.ZONE}", now,
    )  # fmt: skip
    async with engine.begin() as conn:
        await setup.prepare(conn, 1, now, FAST_HASHER)
    statuses = await owner.fetch(
        "SELECT status FROM core.incidents WHERE organization_id = $1", setup.ORGANIZATION
    )
    assert {r["status"] for r in statuses} == {"resolved"}


async def test_unevaluated_readings_are_counted_for_the_organization_only(
    engine: AsyncEngine,
) -> None:
    now = SystemClock().now()
    async with engine.begin() as conn:
        [station] = await setup.prepare(conn, 1, now, FAST_HASHER)
        reading = ClassifiedReading(now - timedelta(seconds=1), 3.0, Quality.OK)
        await SqlReadingWriter(conn).store_and_enqueue(
            station.id, setup.ORGANIZATION, [reading], now, reading, uuid4()
        )
    async with engine.connect() as conn:
        assert await checks.stored(conn, setup.ORGANIZATION, now) == 1
        assert await checks.unevaluated(conn, setup.ORGANIZATION, now) == 1  # not evaluated yet
        later = now + timedelta(seconds=1)
        assert await checks.unevaluated(conn, setup.ORGANIZATION, later) == 0
