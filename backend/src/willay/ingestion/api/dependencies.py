"""Station authentication by API key (X-Api-Key header) and rate limiting.

Not `Authorization`, so station keys never mix with user JWTs. Codes: 401 missing or invalid
key; 403 inactive station; 429 over 30 wrong keys a minute from one address, or over 60
batches a minute from one station.

Each step holds at most one connection at a time (credential read, key-failure counter, batch
counter, batch write): a request holding one while asking for another could deadlock the
pool under load.
"""

from typing import Annotated

from fastapi import Depends, Request, Security, status
from fastapi.security import APIKeyHeader

from willay.ingestion.application.authenticate_station import (
    AuthenticatedStation,
    InactiveStationError,
    InvalidApiKeyError,
    authenticate_station,
)
from willay.ingestion.application.rate_limit import KeyFailureLimit, enforce_rate_limit
from willay.ingestion.domain.rate_limit import (
    MAX_BATCHES_PER_MINUTE,
    MAX_KEY_FAILURES_PER_MINUTE,
    KeyFailuresExceededError,
    RateLimitExceededError,
)
from willay.ingestion.infrastructure.api_keys import ApiKeyHasher, Argon2ApiKeyIssuer
from willay.ingestion.infrastructure.repositories import (
    SqlBatchCounter,
    SqlKeyFailureCounter,
    SqlStationCredentials,
)
from willay.shared.errors import ErrorCode
from willay.shared.web import ApiError, ClockDep, EngineDep

_api_key = APIKeyHeader(
    name="X-Api-Key",
    auto_error=False,
    description="The station's API key: `<station_id>.<secret>`",
)


def get_api_key_hasher(request: Request) -> ApiKeyHasher:
    hasher: ApiKeyHasher = request.app.state.api_key_hasher
    return hasher


def get_api_key_issuer(
    hasher: Annotated[ApiKeyHasher, Depends(get_api_key_hasher)],
) -> Argon2ApiKeyIssuer:
    """New station keys (territory: create a station, rotate its key), hashed like the ones
    this API verifies."""
    return Argon2ApiKeyIssuer(hasher)


async def current_station(
    request: Request,
    engine: EngineDep,
    clock: ClockDep,
    hasher: Annotated[ApiKeyHasher, Depends(get_api_key_hasher)],
    raw_key: Annotated[str | None, Security(_api_key)],
) -> AuthenticatedStation:
    # Behind Caddy, uvicorn's --proxy-headers makes this the sender's address (ADR-0011).
    client = request.client.host if request.client else "unknown"
    try:
        return await authenticate_station(
            raw_key,
            SqlStationCredentials(engine),
            hasher,
            KeyFailureLimit(client, clock, SqlKeyFailureCounter(engine)),
        )
    except KeyFailuresExceededError as exc:
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            ErrorCode.KEY_FAILURES_LIMITED,
            headers={"Retry-After": str(exc.retry_after_s)},
            max=MAX_KEY_FAILURES_PER_MINUTE,
        ) from exc
    except InvalidApiKeyError as exc:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            ErrorCode.API_KEY_INVALID,
            headers={"WWW-Authenticate": "ApiKey"},
        ) from exc
    except InactiveStationError as exc:
        raise ApiError(status.HTTP_403_FORBIDDEN, ErrorCode.STATION_INACTIVE) from exc


async def rate_limited_station(
    station: Annotated[AuthenticatedStation, Depends(current_station)],
    engine: EngineDep,
    clock: ClockDep,
) -> AuthenticatedStation:
    # Counted after authenticating: the limit is per station.
    try:
        await enforce_rate_limit(station.station_id, clock, SqlBatchCounter(engine))
    except RateLimitExceededError as exc:
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            ErrorCode.RATE_LIMITED,
            headers={"Retry-After": str(exc.retry_after_s)},
            max=MAX_BATCHES_PER_MINUTE,
        ) from exc
    return station


IngestingStation = Annotated[AuthenticatedStation, Depends(rate_limited_station)]
