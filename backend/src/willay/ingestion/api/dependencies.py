"""Station authentication by API key (X-Api-Key header) and rate limiting.

Not `Authorization`, so station keys never mix with user JWTs. Codes: 401 missing or invalid
key; 403 inactive station; 429 over 60 batches/min.

Each step holds at most one connection at a time (credential read, counter, batch write): a
request holding one while asking for another could deadlock the pool under load.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from willay.ingestion.application.authenticate_station import (
    AuthenticatedStation,
    InactiveStationError,
    InvalidApiKeyError,
    authenticate_station,
)
from willay.ingestion.application.rate_limit import enforce_rate_limit
from willay.ingestion.domain.rate_limit import MAX_BATCHES_PER_MINUTE, RateLimitExceededError
from willay.ingestion.infrastructure.api_keys import ApiKeyHasher
from willay.ingestion.infrastructure.repositories import SqlBatchCounter, SqlStationCredentials
from willay.shared.web import ClockDep, EngineDep

_api_key = APIKeyHeader(
    name="X-Api-Key",
    auto_error=False,
    description="The station's API key: `<station_id>.<secret>`",
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
    # Counted after authenticating: the limit is per station. Throttling keyless clients
    # (which still cost an Argon2id) is the proxy's job, by IP.
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
