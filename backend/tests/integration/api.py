"""Cliente HTTP contra la app real (Postgres real, JWT firmados por TokenFactory)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
from argon2 import PasswordHasher
from fastapi import APIRouter

from tests.integration.conftest import Database
from tests.support.tokens import ISSUER, TokenFactory
from vigia.api.main import create_app
from vigia.identity.api.dependencies import get_verifier
from vigia.ingestion.infrastructure.api_keys import ApiKeyHasher
from vigia.seed.loader import load_seed
from vigia.shared.clock import SystemClock
from vigia.shared.config import Settings
from vigia.shared.db import create_engine

# Parámetros mínimos de Argon2id: los tests ejercitan el flujo, no el costo del hash.
FAST_HASHER = ApiKeyHasher(PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))


async def ensure_seed(database: Database) -> None:
    """Carga el seed (idempotente): las organizaciones deben existir para resolver el tenant."""
    engine = create_engine(database.app_url)
    try:
        async with engine.begin() as conn:
            await load_seed(conn, SystemClock(), FAST_HASHER)
    finally:
        await engine.dispose()


@asynccontextmanager
async def api_client(
    database: Database, tokens: TokenFactory, *extra_routers: APIRouter
) -> AsyncIterator[httpx2.AsyncClient]:
    await ensure_seed(database)
    app = create_app(Settings(database_url=database.app_url, oidc_issuer=ISSUER))
    for router in extra_routers:
        app.include_router(router)
    app.dependency_overrides[get_verifier] = tokens.verifier
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


def bearer(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token is not None else {}
