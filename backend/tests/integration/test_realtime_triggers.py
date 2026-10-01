"""VIG-25 (ADR-0007): the database announces every incident event and every heartbeat."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import Database
from tests.integration.evaluation import Station
from tests.integration.factories import create_graph, create_rule, link_station
from vigia.shared import notifications
from vigia.shared.db import create_engine

pytestmark = pytest.mark.integration

GT_35_ONCE = {"operator": "gt", "value": 3.5, "consecutive": 1}


@pytest.fixture
async def engine(database: Database) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


async def test_a_reading_that_opens_an_incident_announces_both_changes(
    engine: AsyncEngine, owner: asyncpg.Connection, database: Database
) -> None:
    graph = await create_graph(owner)
    await link_station(owner, graph)
    await create_rule(owner, graph, "threshold", GT_35_ONCE, station_id=graph.station_id)
    heard: list[dict[str, Any]] = []
    listener = await asyncpg.connect(database.app_dsn)
    await listener.add_listener(
        notifications.EVENTS, lambda *args: heard.append(json.loads(args[3]))
    )
    try:
        await Station(engine, graph).send(3.6)  # heartbeat + opened incident, as in ingestion
        mine = [n for n in heard if n["organization_id"] == str(graph.organization_id)]
        async with asyncio.timeout(5):
            while not any(n["type"] == "incident" for n in mine):
                await asyncio.sleep(0.05)
                mine = [n for n in heard if n["organization_id"] == str(graph.organization_id)]
    finally:
        await listener.close()

    stations = [n for n in mine if n["type"] == "station"]
    assert stations[0]["station_id"] == str(graph.station_id)
    assert stations[0]["last_value"] == 3.6
    opened = [n for n in mine if n["type"] == "incident" and n["event"] == "opened"]
    assert len(opened) == 1
    assert set(opened[0]) == {"organization_id", "type", "incident_id", "event"}  # no personal data
