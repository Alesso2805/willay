"""Real Postgres for the integration tests.

Starts the same image as docker-compose (timescaledb-ha) with the same init script, so
roles, extensions and privileges match production, and applies the migrations as
willay_owner. One container per pytest session.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from testcontainers.core.container import DockerContainer

from tests.support.tokens import TokenFactory
from willay.shared.clock import FakeClock, SystemClock

BACKEND_DIR = Path(__file__).resolve().parents[2]
INIT_DIR = BACKEND_DIR.parent / "infra" / "postgres" / "init"
IMAGE = "timescale/timescaledb-ha:pg16-ts2.30"
# Throwaway credentials: the container only lives as long as the test session.
PASSWORDS = {
    "POSTGRES_PASSWORD": "test-postgres",
    "WILLAY_OWNER_PASSWORD": "test-owner",
    "WILLAY_APP_PASSWORD": "test-app",
    "KEYCLOAK_DB_PASSWORD": "test-keycloak",
}


@dataclass(frozen=True)
class Database:
    owner_dsn: str
    app_dsn: str

    @property
    def migrate_url(self) -> str:
        return self.owner_dsn.replace("postgresql://", "postgresql+asyncpg://", 1)

    @property
    def app_url(self) -> str:
        """SQLAlchemy URL for willay_app, like WILLAY_DATABASE_URL in the API and workers."""
        return self.app_dsn.replace("postgresql://", "postgresql+asyncpg://", 1)


def head_revision() -> str:
    """Latest revision in the history, so tests do not hard-code it."""
    head = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini"))).get_current_head()
    assert head is not None
    return head


def _in_own_thread[T](fn: Callable[[], T]) -> T:
    # migrations/env.py calls asyncio.run(), which fails if the thread already has an event
    # loop (pytest-asyncio async tests). A fresh thread has none.
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(fn).result()


def migrate(db: Database, action: str = "upgrade", revision: str = "head") -> None:
    def run() -> None:
        previous = os.environ.get("WILLAY_MIGRATE_DATABASE_URL")
        os.environ["WILLAY_MIGRATE_DATABASE_URL"] = db.migrate_url
        try:
            config = Config(str(BACKEND_DIR / "alembic.ini"))
            getattr(command, action)(config, revision)
        finally:
            if previous is None:
                del os.environ["WILLAY_MIGRATE_DATABASE_URL"]
            else:
                os.environ["WILLAY_MIGRATE_DATABASE_URL"] = previous

    _in_own_thread(run)


async def _wait_until_ready(dsn: str, timeout_s: float = 90.0) -> None:
    # Connecting as willay_owner to the willay database only works once the init script has
    # finished (before that, the temporary server does not listen on TCP and the role does
    # not exist yet).
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        try:
            conn = await asyncpg.connect(dsn, timeout=2)
        except (OSError, asyncpg.PostgresError):
            if asyncio.get_running_loop().time() > deadline:
                raise
            await asyncio.sleep(0.5)
        else:
            await conn.close()
            return


@pytest.fixture(scope="session")
def database() -> Iterator[Database]:
    container = (
        DockerContainer(IMAGE)
        .with_command("postgres -c timescaledb.telemetry_level=off")
        .with_volume_mapping(str(INIT_DIR), "/docker-entrypoint-initdb.d", "ro")
        .with_exposed_ports(5432)
    )
    for key, value in PASSWORDS.items():
        container = container.with_env(key, value)

    with container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5432)
        db = Database(
            owner_dsn=f"postgresql://willay_owner:{PASSWORDS['WILLAY_OWNER_PASSWORD']}@{host}:{port}/willay",
            app_dsn=f"postgresql://willay_app:{PASSWORDS['WILLAY_APP_PASSWORD']}@{host}:{port}/willay",
        )
        _in_own_thread(lambda: asyncio.run(_wait_until_ready(db.owner_dsn)))
        migrate(db)
        yield db


@pytest.fixture
def tokens() -> TokenFactory:
    # Real clock frozen when the fixture is created: tokens must be valid "now" for the
    # app's verifier, which is built with this same clock.
    return TokenFactory(FakeClock(SystemClock().now()))


@pytest.fixture
async def owner(database: Database) -> AsyncIterator[asyncpg.Connection]:
    """Connection as willay_owner (the migrations role)."""
    conn = await asyncpg.connect(database.owner_dsn)
    yield conn
    await conn.close()


@pytest.fixture
async def app(database: Database) -> AsyncIterator[asyncpg.Connection]:
    """Connection as willay_app (the API and workers role)."""
    conn = await asyncpg.connect(database.app_dsn)
    yield conn
    await conn.close()
