"""Caso de uso: de un header X-Api-Key a la estación (y su organización) que envía el lote."""

import asyncio
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from vigia.ingestion.domain.api_keys import parse_api_key


@dataclass(frozen=True)
class StationCredential:
    station_id: UUID
    organization_id: UUID
    api_key_hash: str
    is_active: bool


@dataclass(frozen=True)
class AuthenticatedStation:
    station_id: UUID
    organization_id: UUID  # el tenant sale de la estación, nunca del cuerpo de la petición


class StationCredentials(Protocol):
    async def find(self, station_id: UUID) -> StationCredential | None: ...


class KeyVerifier(Protocol):
    @property
    def dummy_hash(self) -> str: ...

    def verify(self, api_key_hash: str, api_key: str) -> bool: ...


class InvalidApiKeyError(Exception):
    """Clave ausente, mal formada, de una estación inexistente o que no coincide (401)."""


class InactiveStationError(Exception):
    """La clave es correcta pero la estación está desactivada (403)."""


async def authenticate_station(
    raw_key: str | None, credentials: StationCredentials, verifier: KeyVerifier
) -> AuthenticatedStation:
    parsed = parse_api_key(raw_key or "")
    if parsed is None:
        raise InvalidApiKeyError("falta la API key o no tiene el formato <station_id>.<secreto>")

    credential = await credentials.find(parsed.station_id)
    # Argon2id es lento a propósito (~decenas de ms): se ejecuta en un hilo para no
    # bloquear el event loop. Si la estación no existe se verifica igual contra un hash
    # ficticio, para que el tiempo de respuesta no revele qué station_id existen.
    expected_hash = credential.api_key_hash if credential else verifier.dummy_hash
    matches = await asyncio.to_thread(verifier.verify, expected_hash, raw_key or "")
    if credential is None or not matches:
        raise InvalidApiKeyError("API key inválida")
    if not credential.is_active:
        raise InactiveStationError(f"la estación {credential.station_id} está inactiva")
    return AuthenticatedStation(credential.station_id, credential.organization_id)
