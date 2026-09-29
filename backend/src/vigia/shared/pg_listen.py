"""LISTEN de Postgres convertido en un asyncio.Event (ADR-0002).

NOTIFY no es duradero: si esta conexión se cae o nunca se abre, los avisos se pierden.
Por eso los workers también consultan cada pocos segundos; el aviso solo acelera. Si
LISTEN no está disponible, se registra y el worker sigue con la consulta periódica.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import structlog

log = structlog.get_logger()


def asyncpg_dsn(sqlalchemy_url: str) -> str:
    """postgresql+asyncpg://... (SQLAlchemy) → postgresql://... (asyncpg directo)."""
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
