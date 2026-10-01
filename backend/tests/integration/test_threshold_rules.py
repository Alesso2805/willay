"""VIG-15: threshold rules end to end (ingestion → queue → evaluator → incident)."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import Database
from tests.integration.evaluation import Station, incidents, opened_payload
from tests.integration.factories import create_graph, create_rule, link_station
from willay.shared.db import create_engine

pytestmark = pytest.mark.integration

GT_35 = {"operator": "gt", "value": 3.5, "consecutive": 2}


@pytest.fixture
async def engine(database: Database, owner: asyncpg.Connection) -> AsyncIterator[AsyncEngine]:
    await owner.execute("DELETE FROM ingest.evaluation_queue")  # shared database
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


async def _station(
    engine: AsyncEngine, owner: asyncpg.Connection, params: dict[str, Any] = GT_35, **kw: Any
) -> tuple[Station, UUID]:
    graph = await create_graph(owner)
    await link_station(owner, graph)
    rule_id = await create_rule(
        owner, graph, "threshold", params, station_id=graph.station_id, **kw
    )
    return Station(engine, graph), rule_id


async def test_two_consecutive_readings_above_the_limit_open_one_incident(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    station, rule_id = await _station(engine, owner, severity="critical")

    await station.send(3.0, 3.6)
    assert await incidents(owner, station.graph) == []  # only one reading out of bounds

    await station.send(3.7)
    [incident] = await incidents(owner, station.graph)
    graph = station.graph
    assert incident["dedup_key"] == f"{rule_id}:{graph.zone_id}"
    assert (incident["status"], incident["severity"], incident["trigger_value"]) == (
        "open",
        "critical",
        3.7,
    )
    assert (incident["zone_id"], incident["station_id"]) == (graph.zone_id, graph.station_id)

    payload = await opened_payload(owner, incident["id"])
    # The evidence: the readings that fired the rule, in chronological order.
    assert [r["value"] for r in payload["readings"]] == [3.6, 3.7]
    assert payload["rule_params"] == GT_35


async def test_more_readings_above_the_limit_do_not_open_a_second_incident(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    station, _ = await _station(engine, owner)
    await station.send(3.6, 3.7, 3.8, 3.9)
    assert len(await incidents(owner, station.graph)) == 1


async def test_readings_exactly_at_the_limit_do_not_fire(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    station, _ = await _station(engine, owner)
    await station.send(3.5, 3.5, 3.5)
    assert await incidents(owner, station.graph) == []


async def test_a_reading_back_inside_breaks_the_streak(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    station, _ = await _station(engine, owner)
    await station.send(3.6, 3.4, 3.6)
    assert await incidents(owner, station.graph) == []


async def test_late_readings_do_not_break_or_count_in_the_streak(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    station, _ = await _station(engine, owner)
    await station.send(3.6)
    await station.write_late(1.0)  # within bounds, but late: it does not count
    await station.send(3.7)
    assert len(await incidents(owner, station.graph)) == 1


async def test_lower_limit_rules_fire_on_values_below(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    station, _ = await _station(engine, owner, {"operator": "lt", "value": 0.5, "consecutive": 3})
    await station.send(0.4, 0.3)
    assert await incidents(owner, station.graph) == []
    await station.send(0.2)
    assert len(await incidents(owner, station.graph)) == 1


async def test_a_station_without_zone_never_alerts(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    graph = await create_graph(owner)  # no link_station: the station is not in the zone
    await create_rule(owner, graph, "threshold", GT_35, station_id=graph.station_id)
    station = Station(engine, graph)
    await station.send(9.0, 9.0, 9.0)
    assert await incidents(owner, graph) == []


@pytest.mark.parametrize(
    "deactivate",
    [
        pytest.param("UPDATE core.rules SET is_active = false WHERE id = $1", id="inactive-rule"),
        pytest.param(
            "UPDATE core.risk_zones SET is_active = false "
            "WHERE id = (SELECT zone_id FROM core.rules WHERE id = $1)",
            id="inactive-zone",
        ),
    ],
)
async def test_inactive_rules_or_zones_do_not_fire(
    engine: AsyncEngine, owner: asyncpg.Connection, deactivate: str
) -> None:
    station, rule_id = await _station(engine, owner)
    await owner.execute(deactivate, rule_id)
    await station.send(9.0, 9.0)
    assert await incidents(owner, station.graph) == []


async def test_a_zone_wide_rule_applies_to_every_station_in_the_zone(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    graph = await create_graph(owner)
    await link_station(owner, graph)
    await create_rule(owner, graph, "threshold", GT_35)  # null station_id: the whole zone
    station = Station(engine, graph)
    await station.send(4.0, 4.0)
    assert len(await incidents(owner, graph)) == 1


async def test_a_rule_with_broken_params_is_skipped_and_the_others_still_run(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    station, good_rule = await _station(engine, owner)
    await create_rule(
        owner,
        station.graph,
        "threshold",
        {"operator": "between"},
        station_id=station.graph.station_id,
    )

    await station.send(4.0, 4.0)

    [incident] = await incidents(owner, station.graph)
    assert incident["rule_id"] == good_rule
    assert not await owner.fetchval(  # the broken rule did not make the reading fail
        "SELECT count(*) FROM ingest.evaluation_queue WHERE station_id = $1",
        station.graph.station_id,
    )
