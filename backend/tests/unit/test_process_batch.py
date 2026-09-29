import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from vigia.rules.application.evaluate import process_batch
from vigia.rules.application.queue import LostClaimError, QueuedReading

T0 = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)


def _item(queue_id: int, attempt: int = 1) -> QueuedReading:
    return QueuedReading(queue_id, uuid4(), uuid4(), T0, attempt)


class FakeQueue:
    def __init__(self, items: list[QueuedReading], lost: set[int] | None = None) -> None:
        self.items = items
        self.lost = lost or set()
        self.completed: list[int] = []
        self.failed: list[tuple[int, str]] = []

    async def claim(self, limit: int) -> list[QueuedReading]:
        batch, self.items = self.items[:limit], self.items[limit:]
        return batch

    async def complete(self, tx: AsyncConnection, item: QueuedReading) -> None:
        if item.queue_id in self.lost:
            raise LostClaimError(item.queue_id)
        self.completed.append(item.queue_id)

    async def fail(self, item: QueuedReading, error: str) -> bool:
        self.failed.append((item.queue_id, error))
        return item.attempt >= 5


class Transactions:
    """Transacción falsa que registra commits y rollbacks."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncConnection]:
        try:
            yield cast(AsyncConnection, object())
        except BaseException:
            self.rollbacks += 1
            raise
        self.commits += 1


class Evaluator:
    def __init__(self, fails_on: set[int] | None = None) -> None:
        self.fails_on = fails_on or set()

    async def evaluate(self, tx: Any, item: QueuedReading) -> None:
        if item.queue_id in self.fails_on:
            raise ValueError(f"regla rota para {item.queue_id}")


async def test_each_reading_is_evaluated_and_completed_in_its_own_transaction() -> None:
    queue, transactions = FakeQueue([_item(1), _item(2)]), Transactions()
    result = await process_batch(queue, Evaluator(), transactions, limit=10)
    assert (result.claimed, result.completed) == (2, 2)
    assert queue.completed == [1, 2]
    assert transactions.commits == 2


async def test_one_failing_reading_does_not_stop_the_others() -> None:
    queue, transactions = FakeQueue([_item(1), _item(2), _item(3)]), Transactions()
    result = await process_batch(queue, Evaluator(fails_on={2}), transactions, limit=10)

    assert (result.completed, result.failed) == (2, 1)
    assert queue.completed == [1, 3]
    assert queue.failed == [(2, "ValueError: regla rota para 2")]
    assert transactions.rollbacks == 1  # lo escrito para la 2 se revierte


async def test_a_lost_claim_rolls_back_and_is_not_counted_as_a_failure() -> None:
    queue, transactions = FakeQueue([_item(1)], lost={1}), Transactions()
    result = await process_batch(queue, Evaluator(), transactions, limit=10)
    assert (result.lost, result.failed) == (1, 0)
    assert queue.failed == []
    assert transactions.rollbacks == 1


async def test_cancellation_is_not_swallowed() -> None:
    # Parar el proceso no es un fallo de la lectura: no gasta un intento como "fallido";
    # la fila queda tomada y vuelve cuando vence su timeout.
    class Cancelled:
        async def evaluate(self, tx: Any, item: QueuedReading) -> None:
            raise asyncio.CancelledError

    queue = FakeQueue([_item(1)])
    with pytest.raises(asyncio.CancelledError):
        await process_batch(queue, Cancelled(), Transactions(), limit=10)
    assert queue.failed == []
