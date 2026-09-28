"""App FastAPI. Se ejecuta con `uvicorn vigia.api.main:app`.

Los workers nunca arrancan en el lifespan de esta app: son procesos separados. El
lifespan solo crea recursos compartidos por las peticiones (motor de BD, verificador JWT).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from vigia.identity.api.routes import router as identity_router
from vigia.identity.infrastructure.jwt_verifier import JwtVerifier, jwks_key_resolver
from vigia.shared.clock import SystemClock
from vigia.shared.config import Settings, get_settings
from vigia.shared.db import create_engine
from vigia.shared.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        config = settings or get_settings()
        configure_logging(config.log_level)
        app.state.engine = create_engine(config.database_url)
        app.state.verifier = JwtVerifier(
            issuer=config.oidc_issuer,
            audience=config.oidc_audience,
            key_resolver=jwks_key_resolver(config.oidc_jwks_url),
            clock=SystemClock(),
        )
        yield
        await app.state.engine.dispose()

    app = FastAPI(title="Vigía API", version="0.1.0", lifespan=lifespan)

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(identity_router)
    return app


app = create_app()
