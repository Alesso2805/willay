"""Fans out database events to the open SSE connections.

Each connection has its own bounded queue, so a slow client never slows the others or grows
memory. If its queue fills up it is drained and gets a `resync`: better for the dashboard to
reload everything than to show a state with missing changes.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from willay.realtime.domain.events import RealtimeEvent, resync

QUEUE_SIZE = 256


class Subscription:
    def __init__(self, organization_id: UUID, queue_size: int) -> None:
        self.organization_id = organization_id
        self._queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue(queue_size)

    async def next(self) -> RealtimeEvent:
        return await self._queue.get()

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def offer(self, event: RealtimeEvent) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            while not self._queue.empty():
                self._queue.get_nowait()
            self._queue.put_nowait(resync())


class Broadcaster:
    def __init__(self, queue_size: int = QUEUE_SIZE) -> None:
        self._queue_size = queue_size
        self._subscriptions: dict[UUID, set[Subscription]] = {}

    @contextmanager
    def subscribe(self, organization_id: UUID) -> Iterator[Subscription]:
        subscription = Subscription(organization_id, self._queue_size)
        self._subscriptions.setdefault(organization_id, set()).add(subscription)
        try:
            yield subscription
        finally:
            subscriptions = self._subscriptions[organization_id]
            subscriptions.discard(subscription)
            if not subscriptions:
                del self._subscriptions[organization_id]

    def publish(self, event: RealtimeEvent) -> None:
        """Only to the connections of the event's organization."""
        if event.organization_id is None:
            return
        for subscription in self._subscriptions.get(event.organization_id, ()):
            subscription.offer(event)

    def resync_all(self) -> None:
        """To every connection: the database link was lost and any notification may be
        missing."""
        for subscriptions in self._subscriptions.values():
            for subscription in subscriptions:
                subscription.offer(resync())

    @property
    def connections(self) -> int:
        return sum(len(subscriptions) for subscriptions in self._subscriptions.values())
