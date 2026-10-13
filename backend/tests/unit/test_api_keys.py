from typing import Literal
from uuid import UUID

import pytest
from argon2 import PasswordHasher

from willay.ingestion.domain.api_keys import generate_api_key, parse_api_key
from willay.ingestion.infrastructure.api_keys import ApiKeyHasher

STATION = UUID("01a0dc43-cd2d-7522-8430-867cee8f89ce")


def test_generated_key_embeds_station_id_and_a_43_char_secret() -> None:
    key = generate_api_key(STATION)
    parsed = parse_api_key(key)
    assert parsed is not None
    assert parsed.station_id == STATION
    assert len(parsed.secret) == 43


def test_generated_keys_are_unique() -> None:
    assert generate_api_key(STATION) != generate_api_key(STATION)


@pytest.mark.parametrize(
    "raw",
    ["", "no-dot", "not-a-uuid.secret", f"{STATION}.", f".{STATION}"],
)
def test_parse_rejects_malformed_keys(raw: str) -> None:
    assert parse_api_key(raw) is None


def test_hash_is_argon2id_and_verifies_only_the_right_key() -> None:
    hasher = ApiKeyHasher()
    key = generate_api_key(STATION)
    hashed = hasher.hash(key)
    assert hashed.startswith("$argon2id$")
    assert hasher.verify(hashed, key)
    assert not hasher.verify(hashed, generate_api_key(STATION))
    assert not hasher.verify("not-a-hash", key)


class CountingHasher(PasswordHasher):
    """Fast Argon2id parameters, counting how many times the real verification runs."""

    def __init__(self) -> None:
        super().__init__(time_cost=1, memory_cost=8, parallelism=1)
        self.verifications = 0

    def verify(self, hash: str | bytes, password: str | bytes) -> Literal[True]:
        self.verifications += 1
        return super().verify(hash, password)


def test_a_verified_key_is_not_verified_again_with_argon2() -> None:
    counting = CountingHasher()
    hasher = ApiKeyHasher(counting)
    key = generate_api_key(STATION)
    hashed = hasher.hash(key)
    assert all(hasher.verify(hashed, key) for _ in range(5))
    assert counting.verifications == 1


def test_a_wrong_key_always_pays_the_full_cost() -> None:
    counting = CountingHasher()
    hasher = ApiKeyHasher(counting)
    hashed = hasher.hash(generate_api_key(STATION))
    wrong = generate_api_key(STATION)
    assert not any(hasher.verify(hashed, wrong) for _ in range(3))
    assert counting.verifications == 3


def test_rotating_a_key_stops_the_old_one_at_once() -> None:
    # The use case reads the stored hash on every request: rotation changes it.
    hasher = ApiKeyHasher(CountingHasher())
    old_key, new_key = generate_api_key(STATION), generate_api_key(STATION)
    old_hash, new_hash = hasher.hash(old_key), hasher.hash(new_key)
    assert hasher.verify(old_hash, old_key)  # remembered
    assert not hasher.verify(new_hash, old_key)
    assert hasher.verify(new_hash, new_key)


def test_the_cache_is_bounded_and_forgets_the_least_recently_used_key() -> None:
    counting = CountingHasher()
    hasher = ApiKeyHasher(counting, cache_size=2)
    keys = [generate_api_key(STATION) for _ in range(3)]
    hashes = [hasher.hash(key) for key in keys]
    for hashed, key in zip(hashes, keys, strict=True):
        assert hasher.verify(hashed, key)
    assert counting.verifications == 3
    assert hasher.verify(hashes[2], keys[2])  # still remembered
    assert counting.verifications == 3
    assert hasher.verify(hashes[0], keys[0])  # was evicted: verified again
    assert counting.verifications == 4


def test_a_cache_of_size_zero_remembers_nothing() -> None:
    counting = CountingHasher()
    hasher = ApiKeyHasher(counting, cache_size=0)
    key = generate_api_key(STATION)
    hashed = hasher.hash(key)
    assert hasher.verify(hashed, key)
    assert hasher.verify(hashed, key)
    assert counting.verifications == 2
