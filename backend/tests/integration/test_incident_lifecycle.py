"""VIG-18: incidents without duplicates: cooldown, worsening readings and races."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from tests.integration.conftest import Database
from tests.integration.evaluation import Station, incidents
from tests.integration.factories import create_graph, create_rule, link_station
from vigia.alerts.application.planning import AlertPlanner
from vigia.alerts.infrastructure.sql_alerts import SqlAlertRepository
from vigia.incidents.application.open_incident import OpenResult, Trigger
from vigia.incidents.infrastructure.sql_incidents import SqlIncidentStore
from vigia.ingestion.domain.readings import ClassifiedReading, Quality
from vigia.ingestion.infrastructure.repositories import SqlReadingWriter
from vigia.rules.application.evaluate import process_batch
from vigia.rules.application.queue import QueuedReading
from vigia.rules.application.rule_evaluator import RuleEvaluator
from vigia.rules.infrastructure.pg_queue import PostgresEvaluationQueue
from vigia.rules.infrastructure.sql_rules import SqlReadingHistory, SqlRuleRepository
from vigia.shared.clock import FakeClock, SystemClock
from vigia.shared.db import create_engine

pytestmark = pytest.mark.integration

GT_35_ONCE = {"operator": "gt", "value": 3.5, "consecutive": 1}
COOLDOWN = timedelta(seconds=600)  # the one create_rule uses
T0 = datetime(2026, 11, 20, 14, 0, tzinfo=UTC)


@pytest.fixture
async def engine(database: Database, owner: asyncpg.Connection) -> AsyncIterator[AsyncEngine]:
    await owner.execute("DELETE FROM ingest.evaluation_queue")  # shared database
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


async def _station(
    engine: AsyncEngine, owner: asyncpg.Connection, clock: FakeClock | None = None
) -> tuple[Station, UUID]:
    graph = await create_graph(owner)
    await link_station(owner, graph)
    rule_id = await create_rule(owner, graph, "threshold", GT_35_ONCE, station_id=graph.station_id)
    return Station(engine, graph, clock=clock), rule_id


async def _resolve(owner: asyncpg.Connection, incident_id: UUID, at: datetime) -> None:
    await owner.execute(
        "UPDATE core.incidents SET status = 'resolved', resolved_at = $2, resolution = 'resolved'"
        " WHERE id = $1",
        incident_id,
        at,
    )


async def _timeline(owner: asyncpg.Connection, incident_id: UUID) -> list[tuple[str, float]]:
    rows = await owner.fetch(
        "SELECT event_type, payload FROM core.incident_events WHERE incident_id = $1 ORDER BY id",
        incident_id,
    )
    return [(r["event_type"], json.loads(r["payload"]).get("value")) for r in rows]


async def test_a_resolved_cause_does_not_reopen_during_its_cooldown(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    clock = FakeClock(T0)
    station, _ = await _station(engine, owner, clock)
    await station.send(3.6)
    [first] = await incidents(owner, station.graph)
    await _resolve(owner, first["id"], clock.now())

    await station.send(3.7)
    clock.advance(COOLDOWN - timedelta(seconds=1))
    await station.send(3.8)
    assert [i["status"] for i in await incidents(owner, station.graph)] == ["resolved"]

    clock.advance(timedelta(seconds=2))  # the cooldown is over
    await station.send(3.9)
    reopened = await incidents(owner, station.graph)
    assert [(i["status"], i["trigger_value"]) for i in reopened] == [
        ("resolved", 3.6),
        ("open", 3.9),
    ]
    # No incident during the cooldown, but the readings were stored anyway.
    assert (
        await owner.fetchval(
            "SELECT count(*) FROM ingest.readings WHERE station_id = $1",
            station.graph.station_id,
        )
        == 4
    )


async def test_only_readings_that_worsen_an_active_incident_join_its_timeline(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    station, _ = await _station(engine, owner)
    await station.send(3.6, 3.8, 3.7, 3.8, 4.0, 3.9)

    [incident] = await incidents(owner, station.graph)
    assert await _timeline(owner, incident["id"]) == [
        ("opened", None),
        ("reading_added", 3.8),
        ("reading_added", 4.0),
    ]


async def test_reprocessing_a_reading_adds_nothing(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    station, _ = await _station(engine, owner)
    await station.send(3.6, 4.0)
    [incident] = await incidents(owner, station.graph)
    before = await _timeline(owner, incident["id"])

    # The same reading (4.0) evaluated again, as after a queue retry.
    measured_at = await owner.fetchval(
        "SELECT max(measured_at) FROM ingest.readings WHERE station_id = $1",
        station.graph.station_id,
    )
    item = QueuedReading(0, station.graph.station_id, station.graph.organization_id, measured_at, 2)
    async with engine.begin() as tx:
        await station.evaluator.evaluate(tx, item)

    assert len(await incidents(owner, station.graph)) == 1
    assert await _timeline(owner, incident["id"]) == before


class _MeetBeforeOpening(SqlIncidentStore):
    """Makes two evaluators reach the incident opening at the same time."""

    def __init__(self, barrier: asyncio.Barrier) -> None:
        self._barrier = barrier

    async def open(self, tx: AsyncConnection, trigger: Trigger, now: datetime) -> OpenResult:
        await self._barrier.wait()
        return await super().open(tx, trigger, now)


async def test_two_evaluators_racing_on_the_same_cause_open_one_incident(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    station, _ = await _station(engine, owner)
    clock, graph = SystemClock(), station.graph
    async with engine.begin() as tx:
        await SqlReadingWriter(tx).store_and_enqueue(
            graph.station_id,
            graph.organization_id,
            [
                ClassifiedReading(clock.now() - timedelta(seconds=20), 3.6, Quality.OK),
                ClassifiedReading(clock.now() - timedelta(seconds=10), 3.7, Quality.OK),
            ],
            clock.now(),
            None,
        )

    barrier = asyncio.Barrier(2)
    queue = PostgresEvaluationQueue(engine, clock)

    async def evaluator() -> None:
        rules = RuleEvaluator(
            SqlRuleRepository(),
            SqlReadingHistory(),
            _MeetBeforeOpening(barrier),
            clock,
            alerts=AlertPlanner(SqlAlertRepository()),
        )
        await process_batch(queue, rules, engine.begin, limit=1)  # one reading each

    async with asyncio.timeout(10):
        await asyncio.gather(evaluator(), evaluator())

    assert len(await incidents(owner, graph)) == 1
    assert not await owner.fetchval(  # both readings were evaluated
        "SELECT count(*) FROM ingest.evaluation_queue WHERE station_id = $1", graph.station_id
    )
