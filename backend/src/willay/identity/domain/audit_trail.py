"""Reading the audit log (VIG-38): who changed what, most recent first.

Pages are cut with a cursor on (at, id), not with an offset: if new entries arrive while the
admin pages through, an offset would shift and repeat or skip rows; a cursor resumes right
after the last row seen. `id` breaks ties between entries recorded at the same instant.
"""

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

DEFAULT_PAGE = 50
MAX_PAGE = 100


class EntityType(StrEnum):
    """What the audit log records (SPEC: zones, stations, rules, policies and contacts, and
    the organization's own settings)."""

    RISK_ZONE = "risk_zone"
    STATION = "station"
    RULE = "rule"
    ESCALATION_POLICY = "escalation_policy"
    CONTACT = "contact"
    CONTACT_GROUP = "contact_group"
    ORGANIZATION = "organization"  # its language and time zone (VIG-44)


@dataclass(frozen=True)
class Cursor:
    at: datetime
    id: int


class InvalidCursorError(ValueError):
    pass


def encode_cursor(cursor: Cursor) -> str:
    raw = f"{cursor.at.isoformat()}|{cursor.id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(token: str) -> Cursor:
    """Opaque to the client: it only passes back what it received."""
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
        at, entry_id = raw.split("|")
        cursor = Cursor(datetime.fromisoformat(at), int(entry_id))
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise InvalidCursorError(token) from exc
    if cursor.at.tzinfo is None:
        raise InvalidCursorError(token)
    return cursor
