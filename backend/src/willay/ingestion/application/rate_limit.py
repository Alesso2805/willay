"""Use cases: count a batch, or a request's API key check, in its one-minute window and reject
it over the limit."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from willay.ingestion.domain.rate_limit import check_count, check_key_failures, window_start
from willay.shared.clock import Clock


class BatchCounter(Protocol):
    async def hit(self, station_id: UUID, window: datetime) -> int:
        """Atomically add 1 to the window counter and return the total."""
        ...


async def enforce_rate_limit(station_id: UUID, clock: Clock, counter: BatchCounter) -> None:
    now = clock.now()
    count = await counter.hit(station_id, window_start(now))
    check_count(count, now)


class KeyFailureCounter(Protocol):
    async def hit(self, client: str, window: datetime) -> int:
        """Atomically add 1 to the window counter and return the total."""
        ...

    async def refund(self, client: str, window: datetime) -> None: ...


class KeyFailureLimit:
    """A client address's Argon2id checks of wrong keys in the current minute.

    A check is counted before it runs, so a concurrent burst runs no more of them than the
    limit; a key that turns out right takes its count back.
    """

    def __init__(self, client: str, clock: Clock, failures: KeyFailureCounter) -> None:
        self._client = client
        self._clock = clock
        self._failures = failures
        self._window: datetime | None = None

    async def reserve(self) -> None:
        now = self._clock.now()
        self._window = window_start(now)
        check_key_failures(await self._failures.hit(self._client, self._window), now)

    async def release(self) -> None:
        if self._window is not None:
            await self._failures.refund(self._client, self._window)
