"""Autenticación de estaciones por API key (header X-Api-Key) y rate limit.

No usa `Authorization` para no mezclar las claves de estación con los JWT de usuarios.
Códigos: 401 clave ausente o inválida; 403 estación inactiva; 429 más de 60 lotes/min.

Cada paso usa como mucho una conexión a la vez (lectura de la credencial, contador,
escritura del lote). Si una petición retuviera una conexión mientras pide otra, con
carga alta todas podrían quedar esperando una segunda conexión que nunca llega.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from vigia.ingestion.application.authenticate_station import (
    AuthenticatedStation,
    InactiveStationError,
    InvalidApiKeyError,
    authenticate_station,
)
from vigia.ingestion.application.rate_limit import enforce_rate_limit
from vigia.ingestion.domain.rate_limit import MAX_BATCHES_PER_MINUTE, RateLimitExceededError
from vigia.ingestion.infrastructure.api_keys import ApiKeyHasher
from vigia.ingestion.infrastructure.repositories import SqlBatchCounter, SqlStationCredentials
from vigia.shared.web import ClockDep, EngineDep

_api_key = APIKeyHeader(
    name="X-Api-Key",
    auto_error=False,
    description="API key de la estación: `<station_id>.<secreto>`",
)


def get_api_key_hasher(request: Request) -> ApiKeyHasher:
    hasher: ApiKeyHasher = request.app.state.api_key_hasher
    return hasher


async def current_station(
    engine: EngineDep,
    hasher: Annotated[ApiKeyHasher, Depends(get_api_key_hasher)],
    raw_key: Annotated[str | None, Security(_api_key)],
) -> AuthenticatedStation:
    try:
        return await authenticate_station(raw_key, SqlStationCredentials(engine), hasher)
    except InvalidApiKeyError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="API key ausente o inválida",
            headers={"WWW-Authenticate": "ApiKey"},
        ) from exc
    except InactiveStationError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Estación inactiva") from exc


async def rate_limited_station(
    station: Annotated[AuthenticatedStation, Depends(current_station)],
    engine: EngineDep,
    clock: ClockDep,
) -> AuthenticatedStation:
    # Se cuenta después de autenticar: el límite es por estación. Frenar a clientes sin
    # clave (que igual cuestan un Argon2id) es tarea del proxy, por IP.
    try:
        await enforce_rate_limit(station.station_id, clock, SqlBatchCounter(engine))
    except RateLimitExceededError as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Límite de {MAX_BATCHES_PER_MINUTE} lotes por minuto por estación",
            headers={"Retry-After": str(exc.retry_after_s)},
        ) from exc
    return station


IngestingStation = Annotated[AuthenticatedStation, Depends(rate_limited_station)]
