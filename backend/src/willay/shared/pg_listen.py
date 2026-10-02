"""Postgres LISTEN exposed as an asyncio.Event (ADR-0002).

NOTIFY is not durable: while this connection is down, notifications are lost, so workers also
poll every few seconds and the notification only speeds things up. The connection is kept in
the background: if it cannot open (the database is still starting) or drops (the database
restarted), it is retried with a growing wait, and every reconnection wakes the worker once to
catch up with what it may have missed. Without this, a worker would be left polling only
until someone restarted it, with nothing telling.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any

import asyncpg
import structlog

log = structlog.get_logger()

RETRY_FIRST_S = 1.0
RETRY_MAX_S = 30.0

Connect = Callable[[str], Awaitable[Any]]


def asyncpg_dsn(sqlalchemy_url: str) -> str:
    """postgresql+asyncpg://... (SQLAlchemy) -> postgresql://... (plain asyncpg)."""
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@asynccontextmanager
async def listen(
    dsn: str,
    channel: str,
    *,
    retry_first_s: float = RETRY_FIRST_S,
    retry_max_s: float = RETRY_MAX_S,
    connect: Connect = asyncpg.connect,
) -> AsyncIterator[asyncio.Event]:
    """The event is set on every notification on `channel`, and once after each reconnection."""
    event = asyncio.Event()
    keeper = asyncio.create_task(
        _keep_listening(dsn, channel, event, retry_first_s, retry_max_s, connect)
    )
    try:
        yield event
    finally:
        keeper.cancel()
        with suppress(asyncio.CancelledError):
            await keeper


def _setter(event: asyncio.Event) -> Callable[..., None]:
    return lambda *_: event.set()


async def _keep_listening(
    dsn: str,
    channel: str,
    event: asyncio.Event,
    retry_first_s: float,
    retry_max_s: float,
    connect: Connect,
) -> None:
    delay = retry_first_s
    reconnecting = False
    while True:
        lost = asyncio.Event()
        conn: Any = None
        try:
            conn = await connect(dsn)
            await conn.add_listener(channel, _setter(event))
            # Bound to this connection's own event: a closed connection's late callback must
            # never mark the next one as lost.
            conn.add_termination_listener(_setter(lost))
            log.info("listening", channel=channel)
            if reconnecting:
                event.set()  # notifications sent while it was down were lost: catch up once
            delay = retry_first_s
            await lost.wait()
            log.warning("listen_connection_lost", channel=channel)
        # Any failure, not only the expected ones (OSError, a PostgresError such as "the
        # database system is starting up"): if this loop died the worker would poll only.
        except Exception as exc:
            log.warning(
                "listen_unavailable_retrying", channel=channel, error=type(exc).__name__,
                retry_in_s=delay,
            )  # fmt: skip
        finally:
            if conn is not None:
                with suppress(Exception):
                    await conn.close()
        reconnecting = True
        await asyncio.sleep(delay)
        delay = min(delay * 2, retry_max_s)
