"""VIG-09: late readings and NOTIFY to the evaluator, against real Postgres."""

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import asyncpg
import httpx2
import pytest

from tests.integration.api import api_client
from tests.integration.conftest import Database
from tests.integration.factories import Graph, create_station_with_key
from tests.support.tokens import TokenFactory
from willay.ingestion.domain.readings import LATE_AFTER, ClassifiedReading, Quality
from willay.ingestion.infrastructure.repositories import SqlReadingWriter
from willay.shared import notifications
from willay.shared.clock import SystemClock
from willay.shared.db import create_engine

pytestmark = pytest.mark.integration

# Waiting for the *absence* of a notification needs a deadline; it is short because
# locally notifications arrive within milliseconds.
SILENCE_S = 0.5


class Listener:
    """LISTEN on a separate connection, as the evaluator worker does."""

    def __init__(self) -> None:
        self.received = asyncio.Event()
        self.count = 0

    def __call__(self, *_: Any) -> None:
        self.count += 1
        self.received.set()

    async def arrived(self, within_s: float = 5.0) -> bool:
        try:
            await asyncio.wait_for(self.received.wait(), within_s)
        except TimeoutError:
            return False
        return True


@pytest.fixture
async def listener(database: Database) -> AsyncIterator[Listener]:
    conn = await asyncpg.connect(database.app_dsn)
    listener = Listener()
    await conn.add_listener(notifications.EVALUATION_QUEUE, listener)
    yield listener
    await conn.close()


@pytest.fixture
async def client(database: Database, tokens: TokenFactory) -> AsyncIterator[httpx2.AsyncClient]:
    async with api_client(database, tokens) as client:
        yield client


@pytest.fixture
async def station(owner: asyncpg.Connection) -> tuple[Graph, str]:
    return await create_station_with_key(owner)


def _batch(*measured_at: datetime) -> dict[str, Any]:
    return {"readings": [{"measured_at": m.isoformat(), "value": 1.0} for m in measured_at]}


async def test_late_readings_are_stored_but_not_enqueued(
    client: httpx2.AsyncClient, station: tuple[Graph, str], owner: asyncpg.Connection
) -> None:
    graph, key = station
    now = SystemClock().now()
    on_time = now - timedelta(minutes=5)
    late = [now - LATE_AFTER - timedelta(minutes=1), now - timedelta(days=2)]

    response = await client.post(
        "/v1/readings", json=_batch(on_time, *late), headers={"X-Api-Key": key}
    )

    assert response.json() | {"correlation_id": None} == {
        "received": 3, "stored": 3, "duplicates": 0, "late": 2, "correlation_id": None,
    }  # fmt: skip
    qualities = await owner.fetch(
        "SELECT quality FROM ingest.readings WHERE station_id = $1 ORDER BY measured_at",
        graph.station_id,
    )
    assert [q["quality"] for q in qualities] == ["late", "late", "ok"]
    queued = await owner.fetch(
        "SELECT measured_at FROM ingest.evaluation_queue WHERE station_id = $1", graph.station_id
    )
    assert [q["measured_at"] for q in queued] == [on_time]


async def test_accepted_batch_wakes_up_the_evaluator(
    client: httpx2.AsyncClient, station: tuple[Graph, str], listener: Listener
) -> None:
    _, key = station
    await client.post("/v1/readings", json=_batch(SystemClock().now()), headers={"X-Api-Key": key})
    assert await listener.arrived()


@pytest.mark.parametrize("kind", ["only-duplicates", "only-late"])
async def test_nothing_enqueued_means_no_notification(
    client: httpx2.AsyncClient, station: tuple[Graph, str], database: Database, kind: str
) -> None:
    _, key = station
    now = SystemClock().now()
    if kind == "only-duplicates":
        await client.post("/v1/readings", json=_batch(now), headers={"X-Api-Key": key})
        body = _batch(now)
    else:
        body = _batch(now - timedelta(hours=3))

    # Listen only after the first post: only the second batch's notification matters.
    conn = await asyncpg.connect(database.app_dsn)
    listener = Listener()
    await conn.add_listener(notifications.EVALUATION_QUEUE, listener)
    try:
        response = await client.post("/v1/readings", json=body, headers={"X-Api-Key": key})
        assert response.status_code == 202
        assert not await listener.arrived(within_s=SILENCE_S)
    finally:
        await conn.close()


async def test_notification_is_delivered_only_after_commit(
    database: Database, station: tuple[Graph, str], listener: Listener
) -> None:
    graph, _ = station
    now = SystemClock().now()
    engine = create_engine(database.app_url)
    try:
        async with engine.connect() as conn:
            transaction = await conn.begin()
            counts = await SqlReadingWriter(conn).store_and_enqueue(
                graph.station_id,
                graph.organization_id,
                [reading := ClassifiedReading(now, 1.0, Quality.OK)],
                now,
                reading,
                uuid4(),
            )
            assert counts.enqueued == 1
            # Rows written and NOTIFY issued, but the transaction is still open, so nobody
            # hears it yet: the evaluator must not wake up for rows it cannot see.
            assert not await listener.arrived(within_s=SILENCE_S)

            await transaction.commit()
            assert await listener.arrived()
    finally:
        await engine.dispose()


async def test_rolled_back_batch_never_notifies(
    database: Database, station: tuple[Graph, str], listener: Listener, owner: asyncpg.Connection
) -> None:
    graph, _ = station
    now = SystemClock().now()
    engine = create_engine(database.app_url)
    try:
        async with engine.connect() as conn:
            transaction = await conn.begin()
            await SqlReadingWriter(conn).store_and_enqueue(
                graph.station_id,
                graph.organization_id,
                [reading := ClassifiedReading(now, 1.0, Quality.OK)],
                now,
                reading,
                uuid4(),
            )
            await transaction.rollback()
    finally:
        await engine.dispose()

    assert not await listener.arrived(within_s=SILENCE_S)
    assert not await owner.fetchval(
        "SELECT count(*) FROM ingest.evaluation_queue WHERE station_id = $1", graph.station_id
    )
