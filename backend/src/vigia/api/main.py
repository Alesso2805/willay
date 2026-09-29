"""App FastAPI. Se ejecuta con `uvicorn --factory vigia.api.main:create_app`.

Con --factory no hay un `app` global: importar este módulo no lee el entorno, y los
tests construyen la app con su propia configuración.

Los workers nunca arrancan en el lifespan de esta app: son procesos separados. El
lifespan solo crea recursos compartidos por las peticiones (motor de BD, verificador JWT).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from vigia.identity.api.routes import router as identity_router
from vigia.identity.infrastructure.jwt_verifier import JwtVerifier, jwks_key_resolver
from vigia.incidents.api.routes import router as incidents_router
from vigia.ingestion.api.routes import router as ingestion_router
from vigia.ingestion.infrastructure.api_keys import ApiKeyHasher
from vigia.shared.clock import SystemClock
from vigia.shared.config import Settings, get_settings
from vigia.shared.db import create_engine
from vigia.shared.logging import configure_logging
from vigia.shared.web import validation_error_handler
from vigia.territory.api.stations import router as stations_router
from vigia.territory.api.zones import router as zones_router


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(config.log_level)
        app.state.clock = SystemClock()
        app.state.engine = create_engine(config.database_url)
        app.state.api_key_hasher = ApiKeyHasher()
        app.state.verifier = JwtVerifier(
            issuer=config.oidc_issuer,
            audience=config.oidc_audience,
            key_resolver=jwks_key_resolver(config.oidc_jwks_url),
            clock=app.state.clock,
        )
        yield
        await app.state.engine.dispose()

    app = FastAPI(title="Vigía API", version="0.1.0", lifespan=lifespan)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    # El JWT va en el header Authorization (nunca cookies): no hace falta allow_credentials.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        # X-Api-Key no se lista: lo usan estaciones (servidor a servidor), no el navegador.
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
    return app
