"""Reparte los eventos de la base entre las conexiones SSE abiertas (VIG-25).

Cada conexión tiene su propia cola, acotada: un cliente lento nunca frena a los demás ni
hace crecer la memoria. Si su cola se llena, se vacía y recibe un `resync`: es mejor que
el panel vuelva a pedir todo que mostrar un estado al que le faltan cambios.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from vigia.realtime.domain.events import RealtimeEvent, resync

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
        """Solo a las conexiones de la organización del evento."""
        if event.organization_id is None:
            return
        for subscription in self._subscriptions.get(event.organization_id, ()):
            subscription.offer(event)

    def resync_all(self) -> None:
        """A todas: se perdió la conexión con la base y pudo faltar cualquier aviso."""
        for subscriptions in self._subscriptions.values():
            for subscription in subscriptions:
                subscription.offer(resync())

    @property
    def connections(self) -> int:
        return sum(len(subscriptions) for subscriptions in self._subscriptions.values())
