"""Cliente HTTP contra la app real (Postgres real, JWT firmados por TokenFactory)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from fastapi import APIRouter

from tests.integration.conftest import Database
from tests.integration.factories import FAST_HASHER
from tests.support.tokens import ISSUER, TokenFactory
from vigia.api.main import create_app
from vigia.identity.api.dependencies import get_verifier
from vigia.seed.loader import load_seed
from vigia.shared.clock import Clock, SystemClock
from vigia.shared.config import Settings
from vigia.shared.db import create_engine


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
    database: Database,
    tokens: TokenFactory,
    *extra_routers: APIRouter,
    clock: Clock | None = None,
    **settings: Any,
) -> AsyncIterator[httpx2.AsyncClient]:
    """Una instancia de la API. Llamarlo dos veces equivale a dos réplicas: cada una con
    su motor y su pool de conexiones, compartiendo solo la base de datos."""
    await ensure_seed(database)
    app = create_app(Settings(database_url=database.app_url, oidc_issuer=ISSUER, **settings))
    for router in extra_routers:
        app.include_router(router)
    app.dependency_overrides[get_verifier] = tokens.verifier
    async with app.router.lifespan_context(app):
        if clock is not None:
            app.state.clock = clock  # el lifespan pone SystemClock; se reemplaza después
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


def bearer(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token is not None else {}
