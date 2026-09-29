"""`CurrentStation`: autenticación de estaciones por API key (header X-Api-Key).

No usa `Authorization` para no mezclar las claves de estación con los JWT de usuarios.
Códigos: 401 clave ausente o inválida; 403 estación inactiva.
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
from vigia.ingestion.infrastructure.api_keys import ApiKeyHasher
from vigia.ingestion.infrastructure.repositories import SqlStationCredentials
from vigia.shared.web import DbConnection

_api_key = APIKeyHeader(
    name="X-Api-Key",
    auto_error=False,
    description="API key de la estación: `<station_id>.<secreto>`",
)


def get_api_key_hasher(request: Request) -> ApiKeyHasher:
    hasher: ApiKeyHasher = request.app.state.api_key_hasher
    return hasher


async def current_station(
    conn: DbConnection,
    hasher: Annotated[ApiKeyHasher, Depends(get_api_key_hasher)],
    raw_key: Annotated[str | None, Security(_api_key)],
) -> AuthenticatedStation:
    try:
        return await authenticate_station(raw_key, SqlStationCredentials(conn), hasher)
    except InvalidApiKeyError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="API key ausente o inválida",
            headers={"WWW-Authenticate": "ApiKey"},
        ) from exc
    except InactiveStationError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Estación inactiva") from exc


CurrentStation = Annotated[AuthenticatedStation, Depends(current_station)]
