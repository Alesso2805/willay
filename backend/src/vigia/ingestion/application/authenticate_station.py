"""Use case: from an X-Api-Key header to the station (and organization) sending the batch."""

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
    organization_id: UUID  # tenant comes from the station, never from the request body


class StationCredentials(Protocol):
    async def find(self, station_id: UUID) -> StationCredential | None: ...


class KeyVerifier(Protocol):
    @property
    def dummy_hash(self) -> str: ...

    def verify(self, api_key_hash: str, api_key: str) -> bool: ...


class InvalidApiKeyError(Exception):
    """Key missing, malformed, for a nonexistent station, or not matching (401)."""


class InactiveStationError(Exception):
    """The key is valid but the station is deactivated (403)."""


async def authenticate_station(
    raw_key: str | None, credentials: StationCredentials, verifier: KeyVerifier
) -> AuthenticatedStation:
    parsed = parse_api_key(raw_key or "")
    if parsed is None:
        raise InvalidApiKeyError("API key missing or not in the <station_id>.<secret> format")

    credential = await credentials.find(parsed.station_id)
    # Argon2id is slow on purpose (tens of ms), so it runs in a thread to keep the event loop
    # free. Unknown stations are verified against a dummy hash so response time does not
    # reveal which station_ids exist.
    expected_hash = credential.api_key_hash if credential else verifier.dummy_hash
    matches = await asyncio.to_thread(verifier.verify, expected_hash, raw_key or "")
    if credential is None or not matches:
        raise InvalidApiKeyError("invalid API key")
    if not credential.is_active:
        raise InactiveStationError(f"station {credential.station_id} is inactive")
    return AuthenticatedStation(credential.station_id, credential.organization_id)
