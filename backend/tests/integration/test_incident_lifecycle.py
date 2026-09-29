"""VIG-18: incidentes sin duplicados: enfriamiento."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import Database
from tests.integration.evaluation import Station, incidents
from tests.integration.factories import create_graph, create_rule, link_station
from vigia.shared.clock import FakeClock
from vigia.shared.db import create_engine

pytestmark = pytest.mark.integration

GT_35_ONCE = {"operator": "gt", "value": 3.5, "consecutive": 1}
COOLDOWN = timedelta(seconds=600)  # el de create_rule
T0 = datetime(2026, 11, 20, 14, 0, tzinfo=UTC)


@pytest.fixture
async def engine(database: Database, owner: asyncpg.Connection) -> AsyncIterator[AsyncEngine]:
    await owner.execute("DELETE FROM ingest.evaluation_queue")  # base compartida
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

    clock.advance(timedelta(seconds=2))  # el enfriamiento terminó
    await station.send(3.9)
    reopened = await incidents(owner, station.graph)
    assert [(i["status"], i["trigger_value"]) for i in reopened] == [
        ("resolved", 3.6),
        ("open", 3.9),
    ]
    # Durante el enfriamiento no hubo incidente, pero las lecturas se guardaron igual.
    assert (
        await owner.fetchval(
            "SELECT count(*) FROM ingest.readings WHERE station_id = $1",
            station.graph.station_id,
        )
        == 4
    )
