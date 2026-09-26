"""Postgres real para los tests de integración.

Levanta la misma imagen que docker-compose (timescaledb-ha) con el mismo script de
init, así los roles, las extensiones y los permisos son los de producción, y aplica
las migraciones con vigia_owner. Un contenedor por sesión de pytest.
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
from testcontainers.core.container import DockerContainer

BACKEND_DIR = Path(__file__).resolve().parents[2]
INIT_DIR = BACKEND_DIR.parent / "infra" / "postgres" / "init"
IMAGE = "timescale/timescaledb-ha:pg16-ts2.30"
# Credenciales desechables: el contenedor vive lo que dura la sesión de tests.
PASSWORDS = {
    "POSTGRES_PASSWORD": "test-postgres",
    "VIGIA_OWNER_PASSWORD": "test-owner",
    "VIGIA_APP_PASSWORD": "test-app",
    "KEYCLOAK_DB_PASSWORD": "test-keycloak",
}


@dataclass(frozen=True)
class Database:
    owner_dsn: str
    app_dsn: str

    @property
    def migrate_url(self) -> str:
        return self.owner_dsn.replace("postgresql://", "postgresql+asyncpg://", 1)


def _in_own_thread[T](fn: Callable[[], T]) -> T:
    # migrations/env.py usa asyncio.run(), que falla si el hilo ya tiene un event loop
    # (tests async de pytest-asyncio). Un hilo nuevo no tiene loop.
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(fn).result()


def migrate(db: Database, action: str = "upgrade", revision: str = "head") -> None:
    def run() -> None:
        previous = os.environ.get("VIGIA_MIGRATE_DATABASE_URL")
        os.environ["VIGIA_MIGRATE_DATABASE_URL"] = db.migrate_url
        try:
            config = Config(str(BACKEND_DIR / "alembic.ini"))
            getattr(command, action)(config, revision)
        finally:
            if previous is None:
                del os.environ["VIGIA_MIGRATE_DATABASE_URL"]
            else:
                os.environ["VIGIA_MIGRATE_DATABASE_URL"] = previous

    _in_own_thread(run)


async def _wait_until_ready(dsn: str, timeout_s: float = 90.0) -> None:
    # Conectar como vigia_owner a la base vigia solo funciona cuando el script de init
    # terminó (antes, el servidor temporal no escucha por TCP y el rol no existe).
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
            owner_dsn=f"postgresql://vigia_owner:{PASSWORDS['VIGIA_OWNER_PASSWORD']}@{host}:{port}/vigia",
            app_dsn=f"postgresql://vigia_app:{PASSWORDS['VIGIA_APP_PASSWORD']}@{host}:{port}/vigia",
        )
        _in_own_thread(lambda: asyncio.run(_wait_until_ready(db.owner_dsn)))
        migrate(db)
        yield db


@pytest.fixture
async def owner(database: Database) -> AsyncIterator[asyncpg.Connection]:
    """Conexión como vigia_owner (el rol de las migraciones)."""
    conn = await asyncpg.connect(database.owner_dsn)
    yield conn
    await conn.close()


@pytest.fixture
async def app(database: Database) -> AsyncIterator[asyncpg.Connection]:
    """Conexión como vigia_app (el rol de la API y los workers)."""
    conn = await asyncpg.connect(database.app_dsn)
    yield conn
    await conn.close()
