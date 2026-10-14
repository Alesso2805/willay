"""SQLAlchemy async engine and sessions (asyncpg)."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# How a use case opens its own transactions (usually `engine.begin`): one per reading, per
# incident or per update, so that one failure does not roll back the others.
Transaction = Callable[[], AbstractAsyncContextManager[AsyncConnection]]


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: objects stay readable after commit without another query.
    return async_sessionmaker(engine, expire_on_commit=False)
