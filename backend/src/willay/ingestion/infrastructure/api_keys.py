"""Argon2id hashing of station API keys (the format lives in domain/api_keys.py)."""

import hashlib
import threading
from collections import OrderedDict
from functools import cached_property
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from willay.ingestion.domain.api_keys import generate_api_key

# Keys verified by this process. Each station sends a batch every few seconds and Argon2id costs
# 50 to 130 ms of CPU by machine, so without this 50 stations sending together queue up for
# seconds on 4 CPUs (VIG-29).
VERIFIED_CACHE_SIZE = 4096


class ApiKeyHasher:
    """Argon2id with argon2-cffi defaults (RFC 9106 low-memory profile).

    A successful verification is remembered, per process, as the pair (stored hash, SHA-256 of
    the key presented). The stored hash is read from the database on every request, so rotating a
    key changes it and the old key stops matching at once, as the spec requires. Failures are
    never remembered: a wrong key or an unknown station always pays the full Argon2id cost.
    """

    def __init__(
        self, hasher: PasswordHasher | None = None, *, cache_size: int = VERIFIED_CACHE_SIZE
    ) -> None:
        self._hasher = hasher or PasswordHasher()
        self._cache_size = cache_size
        self._verified: OrderedDict[tuple[str, bytes], None] = OrderedDict()
        self._lock = threading.Lock()  # verify() runs in worker threads

    def hash(self, api_key: str) -> str:
        return self._hasher.hash(api_key)

    def verify(self, api_key_hash: str, api_key: str) -> bool:
        entry = (api_key_hash, hashlib.sha256(api_key.encode()).digest())
        with self._lock:
            if entry in self._verified:
                self._verified.move_to_end(entry)
                return True
        try:
            matches = self._hasher.verify(api_key_hash, api_key)
        except (VerificationError, InvalidHashError):
            return False
        if matches and self._cache_size > 0:
            with self._lock:
                self._verified[entry] = None
                while len(self._verified) > self._cache_size:
                    self._verified.popitem(last=False)
        return matches

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
