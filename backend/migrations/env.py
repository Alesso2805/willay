"""Entorno de Alembic: migraciones async con el rol vigia_owner.

Las migraciones se escriben a mano con SQL explícito (ADR-0006): la DDL de TimescaleDB
y PostGIS no se autogenera, así que no hay `target_metadata`.
"""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _database_url() -> str:
    url = os.environ.get("VIGIA_MIGRATE_DATABASE_URL")
    if not url:
        raise RuntimeError("Falta VIGIA_MIGRATE_DATABASE_URL (URL de vigia_owner)")
    return url


def run_migrations_offline() -> None:
    context.configure(url=_database_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    # transaction_per_migration: si la 0003 falla, la 0001 y la 0002 quedan aplicadas.
    context.configure(connection=connection, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_database_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
