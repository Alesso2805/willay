"""Evaluation queue interface (ADR-0002): moving off Postgres (Redis Streams, Kafka) only
changes the implementation, not the domain or the worker loop. Every implementation guarantees:
- `claim` commits attempts + 1 and the visibility timeout in its own transaction BEFORE
  evaluating, so the counter survives a worker crash and the row returns after the timeout.
- `complete` runs in the evaluation transaction: its writes and the row removal commit together.
- After MAX_ATTEMPTS attempts the row is marked failed and stops blocking the queue.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

VISIBILITY_TIMEOUT = timedelta(seconds=60)
MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class QueuedReading:
    queue_id: int
    station_id: UUID
    organization_id: UUID
    measured_at: datetime
    attempt: int  # this attempt's number, 1..MAX_ATTEMPTS
    correlation_id: UUID | None = None  # None for rows enqueued before VIG-28


class LostClaimError(Exception):
    """The visibility timeout expired and another worker reclaimed the row: this evaluation
    is discarded (rollback) so nothing is written twice."""


class EvaluationQueue(Protocol):
    async def claim(self, limit: int) -> list[QueuedReading]:
        """Claims up to `limit` available rows in its own short transaction."""
        ...

    async def complete(self, tx: AsyncConnection, item: QueuedReading) -> None:
        """Marks the reading as evaluated and removes it from the queue inside `tx` (the
        evaluation transaction). Raises LostClaimError if the row is no longer ours."""
        ...

    async def fail(self, item: QueuedReading, error: str) -> bool:
        """Records the error in its own transaction. Returns True if the row is now
        permanently failed (last attempt)."""
        ...
