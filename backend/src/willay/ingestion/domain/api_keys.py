"""Station API key format: `<station_id>.<secret>`.

The secret is 32 random bytes in base64url (43 chars). The station id travels in clear so the
station is found without trying every hash (Argon2id is not searchable). The plaintext key is
shown once and never stored: only its hash (see infrastructure/api_keys.py).
"""

import secrets
from dataclasses import dataclass
from uuid import UUID

_SECRET_BYTES = 32


@dataclass(frozen=True)
class ParsedApiKey:
    station_id: UUID
    secret: str


def generate_api_key(station_id: UUID) -> str:
    return f"{station_id}.{secrets.token_urlsafe(_SECRET_BYTES)}"


def parse_api_key(raw: str) -> ParsedApiKey | None:
    station_part, sep, secret = raw.partition(".")
    if not sep or not secret:
        return None
    try:
        station_id = UUID(station_part)
    except ValueError:
        return None
    return ParsedApiKey(station_id, secret)
