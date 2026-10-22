"""HTTP client against the real app (real Postgres, JWTs signed by TokenFactory)."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
import uvicorn
from fastapi import APIRouter

from tests.integration.conftest import Database
from tests.integration.factories import FAST_HASHER
from tests.support.tokens import ISSUER, TokenFactory
from willay.api.main import create_app
from willay.identity.api.dependencies import get_verifier
from willay.seed.loader import load_seed
from willay.shared.clock import Clock, SystemClock
from willay.shared.config import Settings
from willay.shared.db import create_engine


async def ensure_seed(database: Database) -> None:
    """Loads the seed (idempotent): the organizations must exist to resolve the tenant."""
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
    client_address: str = "127.0.0.1",
    **settings: Any,
) -> AsyncIterator[httpx2.AsyncClient]:
    """One API instance. Calling it twice is like running two replicas: each has its own
    engine and connection pool, and they share only the database."""
    await ensure_seed(database)
    app = create_app(Settings(database_url=database.app_url, oidc_issuer=ISSUER, **settings))
    for router in extra_routers:
        app.include_router(router)
    app.dependency_overrides[get_verifier] = tokens.verifier
    async with app.router.lifespan_context(app):
        if clock is not None:
            app.state.clock = clock  # the lifespan sets SystemClock; replace it afterwards
        transport = httpx2.ASGITransport(app=app, client=(client_address, 123))
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@asynccontextmanager
async def serve_api(database: Database, tokens: TokenFactory) -> AsyncIterator[str]:
    """The same app served by uvicorn on a free port; yields its base URL.

    Needed for responses that never end (SSE): httpx2's ASGI transport waits for the full
    response before returning it, so a stream would never arrive.
    """
    await ensure_seed(database)
    app = create_app(Settings(database_url=database.app_url, oidc_issuer=ISSUER))
    app.dependency_overrides[get_verifier] = tokens.verifier
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    serving = asyncio.create_task(server.serve())
    try:
        for _ in range(500):  # uvicorn exposes no startup event: wait up to 10 s
            if server.started:
                break
            await asyncio.sleep(0.02)
        else:
            raise RuntimeError("uvicorn did not start")
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        server.force_exit = True  # do not wait for open streams to close
        await serving


def bearer(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token is not None else {}
