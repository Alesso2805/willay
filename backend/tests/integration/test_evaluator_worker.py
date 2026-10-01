"""VIG-14b: the evaluator process (run_evaluator) against real Postgres.

"Killing the worker" is simulated by cancelling its task mid-evaluation: as with a SIGKILL,
the open transaction never commits and Postgres discards it.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.conftest import Database
from tests.integration.factories import Graph, create_graph
from willay.ingestion.domain.readings import ClassifiedReading, Quality
from willay.ingestion.infrastructure.repositories import SqlReadingWriter
from willay.rules.application.queue import MAX_ATTEMPTS, VISIBILITY_TIMEOUT, QueuedReading
from willay.shared.clock import FakeClock, SystemClock
from willay.shared.config import Settings
from willay.shared.db import create_engine
from willay.workers.evaluator import run_evaluator

pytestmark = pytest.mark.integration


@pytest.fixture
async def graph(owner: asyncpg.Connection) -> Graph:
    # Shared database: empty the queue so the workers only see this test's rows.
    await owner.execute("DELETE FROM ingest.evaluation_queue")
    return await create_graph(owner)


@pytest.fixture
def settings(database: Database, tmp_path: Path) -> Settings:
    return Settings(database_url=database.app_url, heartbeat_dir=tmp_path)


async def _enqueue(owner: asyncpg.Connection, graph: Graph, at: datetime, count: int) -> None:
    for i in range(count):
        measured = at - timedelta(seconds=count - i)
        await owner.execute(
            "INSERT INTO ingest.readings (station_id, organization_id, measured_at, received_at,"
            " value, quality) VALUES ($1, $2, $3, $4, $5, 'ok')",
            graph.station_id, graph.organization_id, measured, at, float(i),
        )  # fmt: skip
        await owner.execute(
            "INSERT INTO ingest.evaluation_queue (station_id, measured_at, organization_id,"
            " enqueued_at, available_at) VALUES ($1, $2, $3, $4, $4)",
            graph.station_id, measured, graph.organization_id, at,
        )  # fmt: skip


async def _eventually(check: Callable[[], Awaitable[bool]], within_s: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + within_s
    while not await check():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("the condition was not met in time")
        await asyncio.sleep(0.05)


def _start(settings: Settings, stop: asyncio.Event, **kwargs: Any) -> asyncio.Task[None]:
    return asyncio.create_task(run_evaluator(settings, stop, **kwargs))


async def _queue_empty(owner: asyncpg.Connection) -> bool:
    return not await owner.fetchval("SELECT count(*) FROM ingest.evaluation_queue")


async def test_a_notify_wakes_the_worker_long_before_the_polling_interval(
    database: Database, settings: Settings, graph: Graph, owner: asyncpg.Connection
) -> None:
    stop = asyncio.Event()
    worker = _start(settings, stop, poll_interval_s=60.0)
    await asyncio.sleep(0.5)  # first loop is empty; it now listens and sleeps 60 s

    now = SystemClock().now()
    engine = create_engine(database.app_url)
    try:
        async with engine.begin() as tx:  # like ingestion: reading + queue + NOTIFY, one commit
            reading = ClassifiedReading(now, 3.2, Quality.OK)
            await SqlReadingWriter(tx).store_and_enqueue(
                graph.station_id, graph.organization_id, [reading], now, reading
            )
    finally:
        await engine.dispose()
    started = asyncio.get_running_loop().time()

    await _eventually(lambda: _queue_empty(owner), within_s=5.0)
    assert asyncio.get_running_loop().time() - started < 5.0  # it did not wait the 60 s
    assert await owner.fetchval(
        "SELECT evaluated_at IS NOT NULL FROM ingest.readings WHERE station_id = $1",
        graph.station_id,
    )
    stop.set()
    await asyncio.wait_for(worker, timeout=5)


async def test_killing_the_worker_mid_evaluation_leaves_the_row_for_a_retry(
    settings: Settings, graph: Graph, owner: asyncpg.Connection
) -> None:
    clock = FakeClock(SystemClock().now())
    await _enqueue(owner, graph, clock.now(), 1)
    entered = asyncio.Event()

    class HangsForever:
        async def evaluate(self, tx: AsyncConnection, item: QueuedReading) -> None:
            await tx.execute(text("SELECT 1"))  # leaves the transaction open
            entered.set()
            await asyncio.Event().wait()

    stop = asyncio.Event()
    worker = _start(settings, stop, clock=clock, evaluator=HangsForever(), poll_interval_s=0.05)
    await asyncio.wait_for(entered.wait(), timeout=5)
    worker.cancel()  # "kill" the process mid-evaluation
    with pytest.raises(asyncio.CancelledError):
        await worker

    row = await owner.fetchrow("SELECT attempts, available_at FROM ingest.evaluation_queue")
    assert row is not None
    assert (row["attempts"], row["available_at"]) == (1, clock.now() + VISIBILITY_TIMEOUT)
    assert not await owner.fetchval(
        "SELECT evaluated_at FROM ingest.readings WHERE station_id = $1", graph.station_id
    )

    clock.advance(VISIBILITY_TIMEOUT + timedelta(seconds=1))  # the timeout expires
    stop = asyncio.Event()
    survivor = _start(settings, stop, clock=clock, poll_interval_s=0.05)
    await _eventually(lambda: _queue_empty(owner))
    stop.set()
    await asyncio.wait_for(survivor, timeout=5)
    assert await owner.fetchval(
        "SELECT evaluated_at IS NOT NULL FROM ingest.readings WHERE station_id = $1",
        graph.station_id,
    )


async def test_two_workers_evaluate_every_row_exactly_once(
    settings: Settings, graph: Graph, owner: asyncpg.Connection
) -> None:
    await _enqueue(owner, graph, SystemClock().now(), 60)
    seen: list[int] = []

    class Records:
        async def evaluate(self, tx: AsyncConnection, item: QueuedReading) -> None:
            seen.append(item.queue_id)
            await asyncio.sleep(0.005)  # gives both workers time to overlap

    stop = asyncio.Event()
    workers = [
        _start(settings, stop, evaluator=Records(), poll_interval_s=0.05, batch_size=5)
        for _ in range(2)
    ]
    await _eventually(lambda: _queue_empty(owner))
    stop.set()
    await asyncio.wait_for(asyncio.gather(*workers), timeout=5)

    assert len(seen) == 60
    assert len(set(seen)) == 60


async def test_a_poison_row_ends_failed_without_blocking_the_others(
    settings: Settings, graph: Graph, owner: asyncpg.Connection
) -> None:
    clock = FakeClock(SystemClock().now())
    await _enqueue(owner, graph, clock.now(), 5)
    poison = await owner.fetchval("SELECT min(measured_at) FROM ingest.evaluation_queue")

    class FailsOnOne:
        async def evaluate(self, tx: AsyncConnection, item: QueuedReading) -> None:
            if item.measured_at == poison:
                raise ValueError("reading that breaks the rule")

    async def time_passes() -> None:
        while True:  # each loop expires the failed row's visibility timeout
            await asyncio.sleep(0.05)
            clock.advance(VISIBILITY_TIMEOUT + timedelta(seconds=1))

    stop = asyncio.Event()
    ticker = asyncio.create_task(time_passes())
    worker = _start(settings, stop, clock=clock, evaluator=FailsOnOne(), poll_interval_s=0.02)
    try:
        await _eventually(
            lambda: owner.fetchval(
                "SELECT count(*) = 1 AND bool_and(failed_at IS NOT NULL) "
                "FROM ingest.evaluation_queue"
            )
        )
    finally:
        stop.set()
        ticker.cancel()
        await asyncio.wait_for(worker, timeout=5)

    row = await owner.fetchrow("SELECT attempts, last_error FROM ingest.evaluation_queue")
    assert row is not None
    assert row["attempts"] == MAX_ATTEMPTS
    assert "reading that breaks the rule" in row["last_error"]
    evaluated = await owner.fetchval(
        "SELECT count(*) FROM ingest.readings WHERE station_id = $1 AND evaluated_at IS NOT NULL",
        graph.station_id,
    )
    assert evaluated == 4  # the other four were evaluated normally
