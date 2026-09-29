"""VIG-16: reglas de tasa de cambio de punta a punta, con el escenario `drop` del simulador."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import Database
from tests.integration.evaluation import Station, incidents, opened_payload
from tests.integration.factories import create_graph, create_rule, link_station
from vigia.ingestion.domain.simulation import Scenario, build_plan, value_at
from vigia.shared.db import create_engine

pytestmark = pytest.mark.integration

# La regla del seed para la estación aguas abajo del Rímac.
DOWN_40 = {"direction": "down", "delta": 40.0, "window_minutes": 10}
DROP_STEP = 30


@pytest.fixture
async def engine(database: Database, owner: asyncpg.Connection) -> AsyncIterator[AsyncEngine]:
    await owner.execute("DELETE FROM ingest.evaluation_queue")  # base compartida
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
    """Caudal del escenario `drop` (semilla 42): ~85 m3/s con ruido y 34 desde DROP_STEP."""
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
    assert await incidents(owner, station.graph) == []  # el ruido (±2 %) no es una caída

    await station.send(values[DROP_STEP])
    [incident] = await incidents(owner, station.graph)
    assert incident["dedup_key"] == f"{rule_id}:{station.graph.zone_id}"
    assert incident["trigger_value"] == values[DROP_STEP]  # la primera lectura tras la caída

    # Evidencia: la ventana completa, las 30 lecturas previas y la de la caída.
    payload = await opened_payload(owner, incident["id"])
    assert [r["value"] for r in payload["readings"]] == values[: DROP_STEP + 1]
    assert payload["rule_params"] == DOWN_40

    # La caída sigue dentro de la ventana en las lecturas siguientes: mismo incidente.
    await station.send(*values[DROP_STEP + 1 :])
    assert len(await incidents(owner, station.graph)) == 1


async def test_a_slow_decline_never_exceeds_delta_within_the_window(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    # 3 m3/s por minuto durante 24 minutos: 72 en total, pero a lo sumo 30 en 10 minutos.
    station, _ = await _station(engine, owner, interval_s=60)
    await station.send(*(100.0 - 3 * i for i in range(25)))
    assert await incidents(owner, station.graph) == []


@pytest.mark.parametrize(("gap_minutes", "opened"), [(10, 1), (11, 0)])
async def test_the_window_includes_the_reading_exactly_t_minutes_before(
    engine: AsyncEngine, owner: asyncpg.Connection, gap_minutes: int, opened: int
) -> None:
    station, _ = await _station(engine, owner, interval_s=gap_minutes * 60)
    await station.send(100.0, 59.0)  # cae 41 en `gap_minutes`
    assert len(await incidents(owner, station.graph)) == opened


async def test_late_readings_are_not_part_of_the_window(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    station, _ = await _station(engine, owner)
    await station.send(85.0)
    await station.write_late(10.0)  # una caída enorme, pero tardía: no cuenta
    await station.send(84.0)
    assert await incidents(owner, station.graph) == []


async def test_an_up_rule_fires_on_a_sudden_rise(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    params = {"direction": "up", "delta": 1.5, "window_minutes": 5}
    station, _ = await _station(engine, owner, params)

    await station.send(2.0, 2.1, 3.0)
    assert await incidents(owner, station.graph) == []

    await station.send(3.6)  # 2,0 → 3,6 m en 30 s
    [incident] = await incidents(owner, station.graph)
    assert incident["trigger_value"] == 3.6
