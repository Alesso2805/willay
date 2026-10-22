"""Alert delivery: retries and the confirmation token (SPEC: Alerts, Reliability NFR).

A failed send is retried 3 times with exponential backoff (5, 10, 20 s). A duplicate email
beats a lost one, so a send whose result was never stored (worker died) is retried.

The token is 256 random bits in base64url (43 chars, fits Telegram's 64-char
`callback_data`). Only its SHA-256 is stored: with 256 bits of entropy a slow hash like
Argon2 is unnecessary, and reading the database does not allow confirming alerts.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

MAX_ATTEMPTS = 4  # the original send plus 3 retries
FIRST_RETRY = timedelta(seconds=5)
TOKEN_BYTES = 32
TOKEN_TTL = timedelta(hours=24)


def retry_at(failed_attempt: int, now: datetime) -> datetime | None:
    """When to retry after attempt `failed_attempt` (1, 2, ...) failed; None if it was the
    last one."""
    if failed_attempt >= MAX_ATTEMPTS:
        return None
    return now + FIRST_RETRY * int(2 ** (failed_attempt - 1))  # 5, 10, 20 s


@dataclass(frozen=True)
class AckToken:
    token: str  # only travels in the message; never stored
    token_hash: str
    expires_at: datetime


def new_ack_token(now: datetime) -> AckToken:
    return new_token(now, TOKEN_TTL)


def new_token(now: datetime, ttl: timedelta) -> AckToken:
    """A single-use 256-bit token; also used for Telegram linking."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    return AckToken(token, hash_ack_token(token), now + ttl)


def hash_ack_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()
