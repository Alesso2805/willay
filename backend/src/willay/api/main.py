"""FastAPI app, run with `uvicorn --factory willay.api.main:create_app`.

No global `app`: importing this module does not read the environment, and tests build the app
with their own settings. Workers never start in the lifespan (they are separate processes); it
only creates request-shared resources (DB engine, JWT verifier, the LISTEN feeding SSE).
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from willay.alerts.api.confirm_page import router as confirmation_router
from willay.alerts.api.contacts import router as contacts_router
from willay.alerts.api.groups import router as groups_router
from willay.alerts.api.incident_alerts import router as incident_alerts_router
from willay.alerts.api.policies import router as policies_router
from willay.identity.api.routes import router as identity_router
from willay.identity.infrastructure.jwt_verifier import JwtVerifier, jwks_key_resolver
from willay.incidents.api.routes import router as incidents_router
from willay.ingestion.api.routes import router as ingestion_router
from willay.ingestion.infrastructure.api_keys import ApiKeyHasher
from willay.realtime.api.routes import router as realtime_router
from willay.realtime.application.broadcaster import Broadcaster
from willay.realtime.infrastructure.pg_events import PgEventListener
from willay.rules.api.failed_readings import router as failed_readings_router
from willay.shared.clock import SystemClock
from willay.shared.config import Settings, get_settings
from willay.shared.db import create_engine
from willay.shared.logging import configure_logging
from willay.shared.pg_listen import asyncpg_dsn
from willay.shared.web import validation_error_handler
from willay.territory.api.stations import router as stations_router
from willay.territory.api.zones import router as zones_router


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(config.log_level)
        app.state.settings = config
        app.state.clock = SystemClock()
        app.state.engine = create_engine(config.database_url)
        app.state.api_key_hasher = ApiKeyHasher()
        app.state.verifier = JwtVerifier(
            issuer=config.oidc_issuer,
            audience=config.oidc_audience,
            key_resolver=jwks_key_resolver(config.oidc_jwks_url),
            clock=app.state.clock,
        )
        app.state.broadcaster = Broadcaster()
        stop_listening = asyncio.Event()
        listener = PgEventListener(asyncpg_dsn(config.database_url), app.state.broadcaster)
        listening = asyncio.create_task(listener.run(stop_listening))
        yield
        stop_listening.set()
        with contextlib.suppress(asyncio.CancelledError):
            await listening
        await app.state.engine.dispose()

    app = FastAPI(title="Willay API", version="0.1.0", lifespan=lifespan)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    # The JWT goes in the Authorization header (never cookies): no allow_credentials needed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        # X-Api-Key is not listed: stations use it server to server, never the browser.
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(identity_router)
    app.include_router(ingestion_router)
    app.include_router(zones_router)
    app.include_router(stations_router)
    app.include_router(incidents_router)
    app.include_router(incident_alerts_router)
    app.include_router(confirmation_router)
    app.include_router(policies_router)
    app.include_router(contacts_router)
    app.include_router(groups_router)
    app.include_router(failed_readings_router)
    app.include_router(realtime_router)
    return app
