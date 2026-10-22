"""Use case: from an X-Api-Key header to the station (and organization) sending the batch."""

import asyncio
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from willay.ingestion.domain.api_keys import parse_api_key


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

    def remembers(self, api_key_hash: str, api_key: str) -> bool:
        """Whether `verify` would answer from memory, without running Argon2id."""
        ...


class CheckLimit(Protocol):
    async def reserve(self) -> None:
        """Before an Argon2id check; raises when the client is over its limit."""
        ...

    async def release(self) -> None:
        """After a check whose key was right."""
        ...


class InvalidApiKeyError(Exception):
    """Key missing, malformed, for a nonexistent station, or not matching (401)."""


class InactiveStationError(Exception):
    """The key is valid but the station is deactivated (403)."""


async def authenticate_station(
    raw_key: str | None,
    credentials: StationCredentials,
    verifier: KeyVerifier,
    limit: CheckLimit | None = None,
) -> AuthenticatedStation:
    key = raw_key or ""
    parsed = parse_api_key(key)
    if parsed is None:
        raise InvalidApiKeyError("API key missing or not in the <station_id>.<secret> format")

    credential = await credentials.find(parsed.station_id)
    # Argon2id is slow on purpose (50 to 130 ms), so it runs in a thread to keep the event loop
    # free. Unknown stations are verified against a dummy hash so response time does not
    # reveal which station_ids exist.
    expected_hash = credential.api_key_hash if credential else verifier.dummy_hash
    # Only a check that must run Argon2id counts toward the client's limit: a key this process
    # already verified costs nothing, so its station never uses the limit up (ADR-0011).
    reserved = None
    if limit is not None and not verifier.remembers(expected_hash, key):
        await limit.reserve()
        reserved = limit
    matches = await asyncio.to_thread(verifier.verify, expected_hash, key)
    if credential is None or not matches:
        raise InvalidApiKeyError("invalid API key")
    if reserved is not None:
        await reserved.release()
    if not credential.is_active:
        raise InactiveStationError(f"station {credential.station_id} is inactive")
    return AuthenticatedStation(credential.station_id, credential.organization_id)
