"""Evaluator worker use case: process one batch from the queue.

Each reading is evaluated in its own transaction so one failure does not roll back the rest.
Any exception counts as a failed attempt (the row returns after the visibility timeout, or is
marked failed on the fifth attempt). CancelledError (process shutdown) is not caught: the row
stays claimed and reappears when its timeout expires.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from willay.rules.application.queue import EvaluationQueue, LostClaimError, QueuedReading

log = structlog.get_logger()

Transaction = Callable[[], AbstractAsyncContextManager[AsyncConnection]]


class ReadingEvaluator(Protocol):
    async def evaluate(self, tx: AsyncConnection, item: QueuedReading) -> None:
        """Evaluates the rules for the reading and writes incidents and alerts in `tx`."""
        ...


@dataclass(frozen=True)
class BatchResult:
    claimed: int
    completed: int
    failed: int
    lost: int


async def process_batch(
    queue: EvaluationQueue,
    evaluator: ReadingEvaluator,
    transaction: Transaction,
    *,
    limit: int,
) -> BatchResult:
    items = await queue.claim(limit)
    completed = failed = lost = 0
    for item in items:
        bound = log.bind(
            queue_id=item.queue_id,
            station_id=str(item.station_id),
            measured_at=item.measured_at.isoformat(),
            attempt=item.attempt,
        )
        try:
            async with transaction() as tx:
                await evaluator.evaluate(tx, item)
                await queue.complete(tx, item)
            completed += 1
        except LostClaimError:
            lost += 1
            bound.warning("evaluation_lost_claim")
        except Exception as exc:
            failed += 1
            final = await queue.fail(item, f"{type(exc).__name__}: {exc}")
            bound.exception("evaluation_failed", final=final)
    return BatchResult(len(items), completed, failed, lost)
