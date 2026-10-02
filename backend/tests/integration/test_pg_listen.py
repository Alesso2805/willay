"""The workers' LISTEN survives the database dropping its connection, as when Postgres restarts:
it listens again and the worker hears the next notification. Against the real Postgres."""

import asyncio
from uuid import uuid4

import asyncpg
import pytest

from tests.integration.conftest import Database
from willay.shared.pg_listen import listen

pytestmark = pytest.mark.integration


async def _listener_pid(owner: asyncpg.Connection, channel: str) -> int | None:
    pid: int | None = await owner.fetchval(
        "SELECT pid FROM pg_stat_activity WHERE query = $1 AND pid <> pg_backend_pid()",
        f'LISTEN "{channel}"',
    )
    return pid


async def _heard(owner: asyncpg.Connection, channel: str, wakeup: asyncio.Event) -> bool:
    """NOTIFY until the listener wakes (it may still be connecting), for up to 5 s."""
    async with asyncio.timeout(5):
        while not wakeup.is_set():
            await owner.execute(f"NOTIFY {channel}")
            await asyncio.sleep(0.05)
    return True


async def test_the_listener_comes_back_after_its_connection_is_killed(
    database: Database, owner: asyncpg.Connection
) -> None:
    channel = f"test_{uuid4().hex[:12]}"
    async with listen(database.owner_dsn, channel, retry_first_s=0.05, retry_max_s=0.2) as wakeup:
        assert await _heard(owner, channel, wakeup)
        first_pid = await _listener_pid(owner, channel)
        assert first_pid is not None

        # What a Postgres restart does to the worker's connection.
        await owner.execute("SELECT pg_terminate_backend($1)", first_pid)
        async with asyncio.timeout(5):
            # Polling the database's own view: there is no event to wait on.
            while (pid := await _listener_pid(owner, channel)) in (None, first_pid):  # noqa: ASYNC110
                await asyncio.sleep(0.05)
        assert pid != first_pid

        wakeup.clear()
        assert await _heard(owner, channel, wakeup)
