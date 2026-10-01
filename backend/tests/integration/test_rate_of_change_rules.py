"""VIG-16: rate-of-change rules end to end, with the simulator's `drop` scenario."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import Database
from tests.integration.evaluation import Station, incidents, opened_payload
from tests.integration.factories import create_graph, create_rule, link_station
from willay.ingestion.domain.simulation import Scenario, build_plan, value_at
from willay.shared.db import create_engine

pytestmark = pytest.mark.integration

# The seed rule for the Rímac downstream station.
DOWN_40 = {"direction": "down", "delta": 40.0, "window_minutes": 10}
DROP_STEP = 30


@pytest.fixture
async def engine(database: Database, owner: asyncpg.Connection) -> AsyncIterator[AsyncEngine]:
    await owner.execute("DELETE FROM ingest.evaluation_queue")  # shared database
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


async def _station(
    engine: AsyncEngine,
    owner: asyncpg.Connection,
    params: dict[str, Any] = DOWN_40,
    *,
    interval_s: float = 10,
) -> tuple[Station, UUID]:
    graph = await create_graph(owner)
    await link_station(owner, graph)
    rule_id = await create_rule(owner, graph, "rate_of_change", params, station_id=graph.station_id)
    return Station(engine, graph, interval_s=interval_s), rule_id


def _drop_scenario(steps: int) -> list[float]:
    """Discharge of the `drop` scenario (seed 42): ~85 m3/s with noise, then 34 from DROP_STEP."""
    [plan] = build_plan(
        Scenario.DROP, [("RIM-CHA-01", "discharge")], event_step=DROP_STEP, interval_s=10
    )
    values = [value_at(plan, 42, step) for step in range(steps)]
    assert all(v is not None for v in values)
    return [v for v in values if v is not None]


async def test_the_drop_scenario_opens_one_incident_at_the_drop(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    station, rule_id = await _station(engine, owner)
    values = _drop_scenario(DROP_STEP + 15)

    await station.send(*values[:DROP_STEP])
    assert await incidents(owner, station.graph) == []  # the noise (±2 %) is not a drop

    await station.send(values[DROP_STEP])
    [incident] = await incidents(owner, station.graph)
    assert incident["dedup_key"] == f"{rule_id}:{station.graph.zone_id}"
    assert incident["trigger_value"] == values[DROP_STEP]  # the first reading after the drop

    # Evidence: the whole window, the 30 previous readings plus the drop.
    payload = await opened_payload(owner, incident["id"])
    assert [r["value"] for r in payload["readings"]] == values[: DROP_STEP + 1]
    assert payload["rule_params"] == DOWN_40

    # The drop stays inside the window for the next readings: same incident.
    await station.send(*values[DROP_STEP + 1 :])
    assert len(await incidents(owner, station.graph)) == 1


async def test_a_slow_decline_never_exceeds_delta_within_the_window(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    # 3 m3/s per minute for 24 minutes: 72 in total, but at most 30 within 10 minutes.
    station, _ = await _station(engine, owner, interval_s=60)
    await station.send(*(100.0 - 3 * i for i in range(25)))
    assert await incidents(owner, station.graph) == []


@pytest.mark.parametrize(("gap_minutes", "opened"), [(10, 1), (11, 0)])
async def test_the_window_includes_the_reading_exactly_t_minutes_before(
    engine: AsyncEngine, owner: asyncpg.Connection, gap_minutes: int, opened: int
) -> None:
    station, _ = await _station(engine, owner, interval_s=gap_minutes * 60)
    await station.send(100.0, 59.0)  # drops 41 in `gap_minutes`
    assert len(await incidents(owner, station.graph)) == opened


async def test_late_readings_are_not_part_of_the_window(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    station, _ = await _station(engine, owner)
    await station.send(85.0)
    await station.write_late(10.0)  # a huge drop, but late: it does not count
    await station.send(84.0)
    assert await incidents(owner, station.graph) == []


async def test_an_up_rule_fires_on_a_sudden_rise(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    params = {"direction": "up", "delta": 1.5, "window_minutes": 5}
    station, _ = await _station(engine, owner, params)

    await station.send(2.0, 2.1, 3.0)
    assert await incidents(owner, station.graph) == []

    await station.send(3.6)  # 2.0 → 3.6 m in 30 s
    [incident] = await incidents(owner, station.graph)
    assert incident["trigger_value"] == 3.6
