"""The API's LISTEN vigia_events connection (VIG-25, ADR-0007).

One per API process, however many dashboards are connected; events are fanned out in memory.
On connection loss it retries with backoff and, once back, every connection gets a `resync`
(NOTIFY is not durable). It is not a worker (no domain work, it only feeds this process's SSE
responses), so it lives in the API lifespan, like the database engine.
"""

import asyncio
import contextlib
from typing import Any

import asyncpg
import structlog

from vigia.realtime.application.broadcaster import Broadcaster
from vigia.realtime.domain.events import parse_notification
from vigia.shared import notifications

log = structlog.get_logger()

RETRY_INITIAL_S = 1.0
RETRY_MAX_S = 15.0


class PgEventListener:
    def __init__(self, dsn: str, broadcaster: Broadcaster) -> None:
        self._dsn = dsn
        self._broadcaster = broadcaster

    async def run(self, stop: asyncio.Event) -> None:
        delay = RETRY_INITIAL_S
        first = True
        while not stop.is_set():
            try:
                await self._listen_until_lost(stop, resync=not first)
                delay = RETRY_INITIAL_S
            except (OSError, asyncpg.PostgresError) as exc:
                log.warning("events_listen_failed", error=type(exc).__name__, retry_s=delay)
            first = False
            if stop.is_set():
                break
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=delay)
            delay = min(delay * 2, RETRY_MAX_S)

    async def _listen_until_lost(self, stop: asyncio.Event, *, resync: bool) -> None:
        lost = asyncio.Event()
        conn = await asyncpg.connect(self._dsn)
        try:
            conn.add_termination_listener(lambda *_: lost.set())
            await conn.add_listener(notifications.EVENTS, self._on_notify)
            log.info("listening", channel=notifications.EVENTS)
            if resync:
                self._broadcaster.resync_all()
            waiters = [asyncio.create_task(stop.wait()), asyncio.create_task(lost.wait())]
            try:
                await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for waiter in waiters:
                    waiter.cancel()
            if lost.is_set():
                log.warning("listen_connection_lost", channel=notifications.EVENTS)
        finally:
            if not conn.is_closed():
                await conn.close()

    def _on_notify(self, _conn: Any, _pid: int, _channel: str, payload: object) -> None:
        event = parse_notification(str(payload))
        if event is None:
            log.warning("event_notification_unreadable")
            return
        self._broadcaster.publish(event)
