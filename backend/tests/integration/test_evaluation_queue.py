"""VIG-14a: EvaluationQueue on Postgres (SKIP LOCKED, visibility timeout, failed_at)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import Database
from tests.integration.factories import Graph, create_graph
from vigia.rules.application.queue import MAX_ATTEMPTS, VISIBILITY_TIMEOUT, LostClaimError
from vigia.rules.infrastructure.pg_queue import PostgresEvaluationQueue
from vigia.shared.clock import FakeClock
from vigia.shared.db import create_engine

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)


@pytest.fixture
async def engine(database: Database, owner: asyncpg.Connection) -> AsyncIterator[AsyncEngine]:
    # The database is shared and other tests leave queue rows that nobody evaluates yet.
    await owner.execute("DELETE FROM ingest.evaluation_queue")
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(T0)


async def _enqueue(owner: asyncpg.Connection, graph: Graph, count: int) -> list[datetime]:
    """Readings and their queue rows, available from T0."""
    measured = [T0 - timedelta(seconds=10 * (count - i)) for i in range(count)]
    for m in measured:
        await owner.execute(
            "INSERT INTO ingest.readings (station_id, organization_id, measured_at, received_at, "
            "value, quality) VALUES ($1, $2, $3, $4, 1.0, 'ok')",
            graph.station_id, graph.organization_id, m, T0,
        )  # fmt: skip
        await owner.execute(
            "INSERT INTO ingest.evaluation_queue (station_id, measured_at, organization_id, "
            "enqueued_at, available_at) VALUES ($1, $2, $3, $4, $4)",
            graph.station_id, m, graph.organization_id, T0,
        )  # fmt: skip
    return measured


async def _queue(owner: asyncpg.Connection) -> list[asyncpg.Record]:
    return await owner.fetch(
        "SELECT id, attempts, available_at, last_error, failed_at FROM ingest.evaluation_queue "
        "ORDER BY id"
    )


async def test_claim_hides_rows_for_the_visibility_timeout(
    engine: AsyncEngine, clock: FakeClock, owner: asyncpg.Connection
) -> None:
    graph = await create_graph(owner)
    measured = await _enqueue(owner, graph, 3)
    queue = PostgresEvaluationQueue(engine, clock)

    first = await queue.claim(10)

    assert [i.measured_at for i in first] == measured  # in measurement order
    assert {i.attempt for i in first} == {1}
    # The attempt and the timeout are already committed, before anything is evaluated.
    assert {r["available_at"] for r in await _queue(owner)} == {T0 + VISIBILITY_TIMEOUT}
    assert await queue.claim(10) == []  # invisible while the timeout lasts

    clock.advance(VISIBILITY_TIMEOUT + timedelta(seconds=1))
    again = await queue.claim(10)
    assert {i.attempt for i in again} == {2}


async def test_complete_marks_evaluated_and_removes_the_row_in_the_same_transaction(
    engine: AsyncEngine, clock: FakeClock, owner: asyncpg.Connection
) -> None:
    graph = await create_graph(owner)
    await _enqueue(owner, graph, 1)
    queue = PostgresEvaluationQueue(engine, clock)
    [item] = await queue.claim(10)

    async with engine.begin() as tx:
        await queue.complete(tx, item)

    assert await _queue(owner) == []
    evaluated = await owner.fetchval(
        "SELECT evaluated_at FROM ingest.readings WHERE station_id = $1", graph.station_id
    )
    assert evaluated == T0


async def test_a_crash_during_evaluation_rolls_back_and_the_row_comes_back(
    engine: AsyncEngine, clock: FakeClock, owner: asyncpg.Connection
) -> None:
    graph = await create_graph(owner)
    await _enqueue(owner, graph, 1)
    queue = PostgresEvaluationQueue(engine, clock)
    [item] = await queue.claim(10)

    async def crash_before_commit() -> None:
        async with engine.begin() as tx:
            await queue.complete(tx, item)
            raise RuntimeError("the worker dies before the commit")

    with pytest.raises(RuntimeError):
        await crash_before_commit()

    # Everything rolled back: the row is still queued, its attempt counted, and unevaluated.
    [row] = await _queue(owner)
    assert row["attempts"] == 1
    assert not await owner.fetchval(
        "SELECT evaluated_at FROM ingest.readings WHERE station_id = $1", graph.station_id
    )
    clock.advance(VISIBILITY_TIMEOUT + timedelta(seconds=1))
    [retried] = await queue.claim(10)
    assert retried.attempt == 2


async def test_a_worker_that_lost_its_claim_cannot_complete(
    engine: AsyncEngine, clock: FakeClock, owner: asyncpg.Connection
) -> None:
    graph = await create_graph(owner)
    await _enqueue(owner, graph, 1)
    slow, fast = PostgresEvaluationQueue(engine, clock), PostgresEvaluationQueue(engine, clock)
    [stale] = await slow.claim(10)
    clock.advance(VISIBILITY_TIMEOUT + timedelta(seconds=1))
    [fresh] = await fast.claim(10)  # the timeout expired: another worker takes it over

    with pytest.raises(LostClaimError):
        async with engine.begin() as tx:
            await slow.complete(tx, stale)

    async with engine.begin() as tx:
        await fast.complete(tx, fresh)
    assert await _queue(owner) == []


async def test_a_row_that_always_fails_is_marked_failed_at_the_fifth_attempt(
    engine: AsyncEngine, clock: FakeClock, owner: asyncpg.Connection
) -> None:
    graph = await create_graph(owner)
    await _enqueue(owner, graph, 1)
    queue = PostgresEvaluationQueue(engine, clock)

    finals = []
    for _ in range(MAX_ATTEMPTS):
        [item] = await queue.claim(10)
        finals.append(await queue.fail(item, f"fails on attempt {item.attempt}"))
        clock.advance(VISIBILITY_TIMEOUT + timedelta(seconds=1))

    assert finals == [False, False, False, False, True]
    [row] = await _queue(owner)
    assert row["failed_at"] is not None
    assert row["last_error"] == "fails on attempt 5"
    assert await queue.claim(10) == []  # it no longer blocks the queue


async def test_a_row_abandoned_during_its_last_attempt_is_marked_failed(
    engine: AsyncEngine, clock: FakeClock, owner: asyncpg.Connection
) -> None:
    graph = await create_graph(owner)
    await _enqueue(owner, graph, 1)
    # The worker died during the fifth attempt: it never reached complete() or fail().
    await owner.execute("UPDATE ingest.evaluation_queue SET attempts = $1", MAX_ATTEMPTS)

    assert await PostgresEvaluationQueue(engine, clock).claim(10) == []
    [row] = await _queue(owner)
    assert row["failed_at"] == T0
    assert "sin completar tras 5 intentos" in row["last_error"]


async def test_two_evaluators_never_claim_the_same_row(
    database: Database, engine: AsyncEngine, clock: FakeClock, owner: asyncpg.Connection
) -> None:
    graph = await create_graph(owner)
    await _enqueue(owner, graph, 200)
    other_engine = create_engine(database.app_url)  # another process: another connection pool
    try:
        a = PostgresEvaluationQueue(engine, clock)
        b = PostgresEvaluationQueue(other_engine, clock)
        batches = await asyncio.gather(*((a if n % 2 else b).claim(7) for n in range(40)))
    finally:
        await other_engine.dispose()

    claimed = [item.queue_id for batch in batches for item in batch]
    assert len(claimed) == 200
    assert len(set(claimed)) == 200  # no row in two batches
