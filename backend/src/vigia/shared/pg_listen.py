"""Postgres LISTEN exposed as an asyncio.Event (ADR-0002).

NOTIFY is not durable: if this connection drops or never opens, notifications are lost, so
workers also poll every few seconds and the notification only speeds things up. If LISTEN is
unavailable it is logged and the worker keeps polling.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import structlog

log = structlog.get_logger()


def asyncpg_dsn(sqlalchemy_url: str) -> str:
    """postgresql+asyncpg://... (SQLAlchemy) -> postgresql://... (plain asyncpg)."""
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@asynccontextmanager
async def listen(dsn: str, channel: str) -> AsyncIterator[asyncio.Event]:
    event = asyncio.Event()
    conn: asyncpg.Connection | None = None

    def on_notify(*_: Any) -> None:
        event.set()

    def on_lost(*_: Any) -> None:
        log.warning("listen_connection_lost", channel=channel)

    try:
        conn = await asyncpg.connect(dsn)
        await conn.add_listener(channel, on_notify)
        conn.add_termination_listener(on_lost)
        log.info("listening", channel=channel)
    except (OSError, asyncpg.PostgresError) as exc:
        log.warning("listen_unavailable_polling_only", channel=channel, error=type(exc).__name__)
    try:
        yield event
    finally:
        if conn is not None:
            await conn.close()
