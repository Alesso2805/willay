"""Use case: count the batch in its one-minute window and reject it over the limit."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from vigia.ingestion.domain.rate_limit import check_count, window_start
from vigia.shared.clock import Clock


class BatchCounter(Protocol):
    async def hit(self, station_id: UUID, window: datetime) -> int:
        """Atomically add 1 to the window counter and return the total."""
        ...


async def enforce_rate_limit(station_id: UUID, clock: Clock, counter: BatchCounter) -> None:
    now = clock.now()
    count = await counter.hit(station_id, window_start(now))
    check_count(count, now)
