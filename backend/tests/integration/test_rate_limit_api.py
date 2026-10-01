"""VIG-08: 60 batches per minute per station, counted in Postgres and valid with 2 replicas."""

import asyncio
from collections import Counter
from datetime import timedelta
from typing import Any

import asyncpg
import httpx2
import pytest

from tests.integration.api import api_client
from tests.integration.conftest import Database
from tests.integration.factories import Graph, create_station_with_key
from tests.support.tokens import TokenFactory
from willay.ingestion.domain.rate_limit import MAX_BATCHES_PER_MINUTE
from willay.shared.clock import FakeClock, SystemClock

pytestmark = pytest.mark.integration


@pytest.fixture
def clock() -> FakeClock:
    # Frozen, so the test never crosses a minute boundary halfway through.
    return FakeClock(SystemClock().now())


@pytest.fixture
async def station(owner: asyncpg.Connection) -> tuple[Graph, str]:
    return await create_station_with_key(owner)


def _one_reading(clock: FakeClock, n: int) -> dict[str, Any]:
    measured_at = clock.now() - timedelta(seconds=n + 1)
    return {"readings": [{"measured_at": measured_at.isoformat(), "value": float(n)}]}


async def test_limit_is_shared_by_two_api_replicas_under_concurrency(
    database: Database,
    tokens: TokenFactory,
    clock: FakeClock,
    station: tuple[Graph, str],
    owner: asyncpg.Connection,
) -> None:
    graph, key = station
    total = MAX_BATCHES_PER_MINUTE + 10

    async with (
        api_client(database, tokens, clock=clock) as replica_a,
        api_client(database, tokens, clock=clock) as replica_b,
    ):
        # 70 concurrent batches split across two instances with separate pools: only the
        # atomic upsert in Postgres can keep the count exact.
        responses = await asyncio.gather(
            *(
                (replica_a if n % 2 else replica_b).post(
                    "/v1/readings", json=_one_reading(clock, n), headers={"X-Api-Key": key}
                )
                for n in range(total)
            )
        )

    assert Counter(r.status_code for r in responses) == {202: MAX_BATCHES_PER_MINUTE, 429: 10}
    retry_after = {int(r.headers["retry-after"]) for r in responses if r.status_code == 429}
    assert retry_after
    assert all(1 <= s <= 60 for s in retry_after)
    stored = await owner.fetchval(
        "SELECT count(*) FROM ingest.readings WHERE station_id = $1", graph.station_id
    )
    assert stored == MAX_BATCHES_PER_MINUTE  # rejected batches store nothing


async def test_next_minute_opens_a_new_window(
    database: Database, tokens: TokenFactory, clock: FakeClock, station: tuple[Graph, str]
) -> None:
    _, key = station
    async with api_client(database, tokens, clock=clock) as client:

        async def post(n: int) -> httpx2.Response:
            return await client.post(
                "/v1/readings", json=_one_reading(clock, n), headers={"X-Api-Key": key}
            )

        for n in range(MAX_BATCHES_PER_MINUTE):
            assert (await post(n)).status_code == 202
        assert (await post(1000)).status_code == 429

        clock.advance(timedelta(minutes=1))
        assert (await post(2000)).status_code == 202


async def test_invalid_batches_also_count(
    database: Database, tokens: TokenFactory, clock: FakeClock, station: tuple[Graph, str]
) -> None:
    # The limit protects the API from a runaway station, whatever it sends.
    _, key = station
    async with api_client(database, tokens, clock=clock) as client:
        future = clock.now() + timedelta(hours=1)
        invalid = {"readings": [{"measured_at": future.isoformat(), "value": 1.0}]}
        for _ in range(MAX_BATCHES_PER_MINUTE):
            response = await client.post("/v1/readings", json=invalid, headers={"X-Api-Key": key})
            assert response.status_code == 422

        valid = await client.post(
            "/v1/readings", json=_one_reading(clock, 0), headers={"X-Api-Key": key}
        )
        assert valid.status_code == 429


async def test_stations_do_not_share_their_limit(
    database: Database,
    tokens: TokenFactory,
    clock: FakeClock,
    station: tuple[Graph, str],
    owner: asyncpg.Connection,
) -> None:
    _, busy_key = station
    _, quiet_key = await create_station_with_key(owner)
    async with api_client(database, tokens, clock=clock) as client:
        for n in range(MAX_BATCHES_PER_MINUTE + 1):
            await client.post(
                "/v1/readings", json=_one_reading(clock, n), headers={"X-Api-Key": busy_key}
            )
        quiet = await client.post(
            "/v1/readings", json=_one_reading(clock, 0), headers={"X-Api-Key": quiet_key}
        )
        assert quiet.status_code == 202
