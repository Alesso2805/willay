from uuid import UUID

import pytest

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
