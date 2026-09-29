"""VIG-10: latido de estación en ingest.station_heartbeats, contra la app y Postgres reales."""

import asyncio
import random
from datetime import datetime, timedelta
from typing import Any

import asyncpg
import httpx2
import pytest

from tests.integration.api import api_client
from tests.integration.conftest import Database
from tests.integration.factories import Graph, create_station_with_key
from tests.support.tokens import TokenFactory
from vigia.shared.clock import FakeClock, SystemClock

pytestmark = pytest.mark.integration


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(SystemClock().now())


@pytest.fixture
async def station(owner: asyncpg.Connection) -> tuple[Graph, str]:
    return await create_station_with_key(owner)


def _body(*readings: tuple[datetime, float]) -> dict[str, Any]:
    return {"readings": [{"measured_at": m.isoformat(), "value": v} for m, v in readings]}


async def _post(client: httpx2.AsyncClient, key: str, *readings: tuple[datetime, float]) -> Any:
    response = await client.post("/v1/readings", json=_body(*readings), headers={"X-Api-Key": key})
    assert response.status_code == 202, response.text
    return response.json()


async def _heartbeat(owner: asyncpg.Connection, graph: Graph) -> asyncpg.Record | None:
    return await owner.fetchrow(
        "SELECT last_seen_at, last_measured_at, last_value FROM ingest.station_heartbeats "
        "WHERE station_id = $1",
        graph.station_id,
    )


async def test_first_batch_creates_the_heartbeat_from_the_latest_on_time_reading(
    database: Database,
    tokens: TokenFactory,
    clock: FakeClock,
    station: tuple[Graph, str],
    owner: asyncpg.Connection,
) -> None:
    graph, key = station
    t = clock.now()
    async with api_client(database, tokens, clock=clock) as client:
        await _post(
            client,
            key,
            (t - timedelta(seconds=10), 2.0),
            (t - timedelta(hours=2), 9.0),  # tardía: no cuenta aunque su valor sea otro
            (t - timedelta(seconds=30), 1.0),
        )

    assert tuple(await _heartbeat(owner, graph) or ()) == (t, t - timedelta(seconds=10), 2.0)


async def test_a_batch_of_only_late_readings_does_not_beat(
    database: Database,
    tokens: TokenFactory,
    clock: FakeClock,
    station: tuple[Graph, str],
    owner: asyncpg.Connection,
) -> None:
    graph, key = station
    t = clock.now()
    async with api_client(database, tokens, clock=clock) as client:
        await _post(client, key, (t - timedelta(hours=2), 9.0))
        assert await _heartbeat(owner, graph) is None  # ni siquiera se crea

        await _post(client, key, (t - timedelta(seconds=5), 1.0))
        clock.advance(timedelta(minutes=10))
        await _post(client, key, (t - timedelta(hours=3), 8.0))

    # Diez minutos después solo llegaron datos viejos: el latido sigue en t, y el
    # detector de silencio verá a la estación callada, como debe.
    assert tuple(await _heartbeat(owner, graph) or ()) == (t, t - timedelta(seconds=5), 1.0)


async def test_backfill_of_older_readings_refreshes_seen_but_not_the_last_value(
    database: Database,
    tokens: TokenFactory,
    clock: FakeClock,
    station: tuple[Graph, str],
    owner: asyncpg.Connection,
) -> None:
    graph, key = station
    t = clock.now()
    async with api_client(database, tokens, clock=clock) as client:
        await _post(client, key, (t - timedelta(seconds=10), 2.0))
        clock.advance(timedelta(seconds=30))
        # La estación recupera su buffer: lecturas a tiempo pero anteriores a la última.
        await _post(client, key, (t - timedelta(seconds=50), 7.0))

    assert tuple(await _heartbeat(owner, graph) or ()) == (
        t + timedelta(seconds=30),  # está viva ahora
        t - timedelta(seconds=10),  # pero el último dato sigue siendo el mismo
        2.0,
    )


async def test_resending_duplicates_counts_as_alive(
    database: Database,
    tokens: TokenFactory,
    clock: FakeClock,
    station: tuple[Graph, str],
    owner: asyncpg.Connection,
) -> None:
    graph, key = station
    t = clock.now()
    reading = (t - timedelta(seconds=5), 3.0)
    async with api_client(database, tokens, clock=clock) as client:
        await _post(client, key, reading)
        clock.advance(timedelta(seconds=30))
        assert (await _post(client, key, reading))["duplicates"] == 1

    heartbeat = await _heartbeat(owner, graph)
    assert heartbeat is not None
    assert heartbeat["last_seen_at"] == t + timedelta(seconds=30)


async def test_concurrent_batches_from_two_replicas_never_move_the_heartbeat_back(
    database: Database, tokens: TokenFactory, station: tuple[Graph, str], owner: asyncpg.Connection
) -> None:
    graph, key = station
    t = SystemClock().now()
    # Dos réplicas con relojes que difieren 5 s, como dos servidores reales.
    clock_a, clock_b = FakeClock(t), FakeClock(t + timedelta(seconds=5))
    base = t - timedelta(seconds=40)
    order = list(range(20))
    random.Random(7).shuffle(order)  # llegan desordenadas, con semilla fija

    async with (
        api_client(database, tokens, clock=clock_a) as replica_a,
        api_client(database, tokens, clock=clock_b) as replica_b,
    ):
        await asyncio.gather(
            *(
                _post(replica_a if i % 2 else replica_b, key, (base + timedelta(seconds=n), n))
                for i, n in enumerate(order)
            )
        )

    assert tuple(await _heartbeat(owner, graph) or ()) == (
        t + timedelta(seconds=5),  # la recepción más reciente, venga de la réplica que venga
        base + timedelta(seconds=19),  # la medición más reciente
        19.0,  # y su valor, no el del último lote en confirmar
    )
