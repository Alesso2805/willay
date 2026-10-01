"""Argon2id hashing of station API keys (the format lives in domain/api_keys.py)."""

from functools import cached_property
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from willay.ingestion.domain.api_keys import generate_api_key


class ApiKeyHasher:
    """Argon2id with argon2-cffi defaults (RFC 9106 low-memory profile)."""

    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        self._hasher = hasher or PasswordHasher()

    def hash(self, api_key: str) -> str:
        return self._hasher.hash(api_key)

    def verify(self, api_key_hash: str, api_key: str) -> bool:
        try:
            return self._hasher.verify(api_key_hash, api_key)
        except (VerificationError, InvalidHashError):
            return False

    @cached_property
    def dummy_hash(self) -> str:
        """Hash of a key nobody has, with the same parameters as the real ones.

        Verifying against it when the station does not exist equalizes response time.
        """
        return self._hasher.hash("willay-dummy-key-that-never-matches")


class Argon2ApiKeyIssuer:
    """Issues keys for the territory module (create station, rotate key)."""

    def __init__(self, hasher: ApiKeyHasher) -> None:
        self._hasher = hasher

    def issue(self, station_id: UUID) -> tuple[str, str]:
        api_key = generate_api_key(station_id)
        return api_key, self._hasher.hash(api_key)
