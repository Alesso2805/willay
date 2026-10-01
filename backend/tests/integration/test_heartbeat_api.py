"""VIG-10: station heartbeat in ingest.station_heartbeats, against the real app and Postgres."""

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
from willay.shared.clock import FakeClock, SystemClock

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
            (t - timedelta(hours=2), 9.0),  # late: it does not count, even with a different value
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
        assert await _heartbeat(owner, graph) is None  # not even created

        await _post(client, key, (t - timedelta(seconds=5), 1.0))
        clock.advance(timedelta(minutes=10))
        await _post(client, key, (t - timedelta(hours=3), 8.0))

    # Ten minutes later only old data arrived: the heartbeat stays at t, so the silence
    # detector sees the station as quiet, as it should.
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
        # The station flushes its buffer: on-time readings, but older than the latest one.
        await _post(client, key, (t - timedelta(seconds=50), 7.0))

    assert tuple(await _heartbeat(owner, graph) or ()) == (
        t + timedelta(seconds=30),  # alive now
        t - timedelta(seconds=10),  # but the latest data point is unchanged
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
    # Two replicas whose clocks differ by 5 s, like two real servers.
    clock_a, clock_b = FakeClock(t), FakeClock(t + timedelta(seconds=5))
    base = t - timedelta(seconds=40)
    order = list(range(20))
    random.Random(7).shuffle(order)  # they arrive out of order, with a fixed seed

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
        t + timedelta(seconds=5),  # the latest receipt, whichever replica it came from
        base + timedelta(seconds=19),  # the latest measurement
        19.0,  # and its value, not that of the last batch to commit
    )
