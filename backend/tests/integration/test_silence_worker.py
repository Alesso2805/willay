"""VIG-17: el worker silence contra Postgres real, con el tiempo movido por FakeClock."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import Database
from tests.integration.evaluation import incidents, opened_payload
from tests.integration.factories import Graph, add_station, create_graph, create_rule, link_station
from vigia.incidents.infrastructure.sql_incidents import SqlIncidentStore
from vigia.rules.application.silence_check import SilenceChecker
from vigia.rules.infrastructure.sql_silence import SqlSilenceRepository
from vigia.shared.clock import FakeClock
from vigia.shared.config import Settings
from vigia.shared.db import create_engine
from vigia.workers.silence import INTERVAL_S, run_silence

pytestmark = pytest.mark.integration

LAST_SEEN = datetime(2026, 11, 9, 8, 50, tzinfo=UTC)
# Las estaciones de las factories: intervalo de 10 s y K = 3 por defecto.
THRESHOLD = timedelta(seconds=30)


@pytest.fixture
async def engine(database: Database) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


def _checker(engine: AsyncEngine, clock: FakeClock) -> SilenceChecker:
    return SilenceChecker(SqlSilenceRepository(), SqlIncidentStore(), clock, engine.begin)


async def _heartbeat(owner: asyncpg.Connection, station_id: object, value: float = 84.2) -> None:
    await owner.execute(
        "INSERT INTO ingest.station_heartbeats (station_id, last_seen_at, last_measured_at,"
        " last_value, updated_at) VALUES ($1, $2, $3, $4, $2)",
        station_id, LAST_SEEN, LAST_SEEN - timedelta(seconds=2), value,
    )  # fmt: skip


async def _watched_station(owner: asyncpg.Connection) -> Graph:
    """Estación con zona y latido, vigilada por la regla de silencio de create_graph."""
    graph = await create_graph(owner)
    await link_station(owner, graph)
    await _heartbeat(owner, graph.station_id)
    return graph


async def test_the_incident_opens_before_k_times_the_interval_plus_30_s(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    graph = await _watched_station(owner)
    # Ciclos cada 15 s, empezando en una fase cualquiera respecto del último latido.
    clock = FakeClock(LAST_SEEN + timedelta(seconds=7))
    checker = _checker(engine, clock)
    while not await incidents(owner, graph):
        assert clock.now() - LAST_SEEN <= THRESHOLD + timedelta(seconds=INTERVAL_S)
        await checker.run()
        clock.advance(timedelta(seconds=INTERVAL_S))

    [incident] = await incidents(owner, graph)
    opened_at = await owner.fetchval(
        "SELECT opened_at FROM core.incidents WHERE id = $1", incident["id"]
    )
    assert THRESHOLD <= opened_at - LAST_SEEN < THRESHOLD + timedelta(seconds=30)  # SPEC
    assert incident["dedup_key"] == f"{graph.rule_id}:{graph.zone_id}:{graph.station_id}"
    assert (incident["status"], incident["severity"], incident["trigger_value"]) == (
        "open",
        "critical",
        84.2,
    )

    payload = await opened_payload(owner, incident["id"])
    assert payload["rule_type"] == "silence"
    assert [r["value"] for r in payload["readings"]] == [84.2]  # la última lectura conocida
    assert payload["details"] == {
        "last_seen_at": LAST_SEEN.isoformat(),
        "expected_interval_s": 10,
        "silence_multiplier": 3,
    }


async def test_later_cycles_do_not_open_a_second_incident(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    graph = await _watched_station(owner)
    clock = FakeClock(LAST_SEEN + THRESHOLD)
    checker = _checker(engine, clock)
    for _ in range(3):
        await checker.run()
        clock.advance(timedelta(seconds=INTERVAL_S))
    assert len(await incidents(owner, graph)) == 1


async def test_a_zone_wide_rule_opens_one_incident_per_silent_station(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    graph = await _watched_station(owner)
    await owner.execute("UPDATE core.rules SET is_active = false WHERE id = $1", graph.rule_id)
    zone_rule = await create_rule(owner, graph, "silence", {})  # station_id nulo: toda la zona
    second = await add_station(owner, graph, "EST-2")
    await _heartbeat(owner, second)

    await _checker(engine, FakeClock(LAST_SEEN + THRESHOLD)).run()

    opened = await incidents(owner, graph)
    assert {i["station_id"] for i in opened} == {graph.station_id, second}
    assert {i["rule_id"] for i in opened} == {zone_rule}


@pytest.mark.parametrize(
    "setup",
    [
        pytest.param("DELETE FROM core.zone_stations WHERE station_id = $1", id="sin-zona"),
        pytest.param(
            "DELETE FROM ingest.station_heartbeats WHERE station_id = $1", id="nunca-reporto"
        ),
        pytest.param(
            "UPDATE core.stations SET status = 'inactive' WHERE id = $1", id="estacion-inactiva"
        ),
        pytest.param(
            "UPDATE core.rules SET is_active = false WHERE station_id = $1", id="regla-inactiva"
        ),
        pytest.param(
            "UPDATE core.risk_zones SET is_active = false "
            "WHERE id = (SELECT zone_id FROM core.rules WHERE station_id = $1)",
            id="zona-inactiva",
        ),
    ],
)
async def test_stations_that_cannot_alert_are_ignored(
    engine: AsyncEngine, owner: asyncpg.Connection, setup: str
) -> None:
    graph = await _watched_station(owner)
    await owner.execute(setup, graph.station_id)
    await _checker(engine, FakeClock(LAST_SEEN + timedelta(hours=1))).run()
    assert await incidents(owner, graph) == []


async def test_the_worker_process_opens_the_incident(
    database: Database, owner: asyncpg.Connection, tmp_path: Path
) -> None:
    graph = await _watched_station(owner)
    settings = Settings(database_url=database.app_url, heartbeat_dir=tmp_path)
    stop = asyncio.Event()
    worker = asyncio.create_task(
        run_silence(settings, stop, clock=FakeClock(LAST_SEEN + THRESHOLD), interval_s=0.05)
    )
    try:
        deadline = asyncio.get_running_loop().time() + 10
        while not await incidents(owner, graph):
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("el worker no abrió el incidente a tiempo")
            await asyncio.sleep(0.05)
    finally:
        stop.set()
        await worker
    assert (tmp_path / "silence.alive").exists()  # latido del healthcheck
