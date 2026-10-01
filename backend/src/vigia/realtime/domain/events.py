"""Live events for the dashboard (VIG-25).

The database sends a JSON payload via NOTIFY (migration 0008); each one belongs to a single
organization and only reaches that organization's connections (SPEC). Types: `incident` (the
dashboard refetches it over REST, so the viewer's permissions apply), `station` (a heartbeat
with its last value) and `resync` (a notification may have been lost: reload everything).
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

INCIDENT = "incident"
STATION = "station"
RESYNC = "resync"
KINDS = frozenset({INCIDENT, STATION})


@dataclass(frozen=True)
class RealtimeEvent:
    organization_id: UUID | None  # None only for `resync`, which goes to every connection
    type: str
    data: Mapping[str, Any] = field(default_factory=dict)


def resync() -> RealtimeEvent:
    return RealtimeEvent(None, RESYNC)


def parse_notification(payload: str) -> RealtimeEvent | None:
    """The event for a database notification, or None if unreadable or of an unknown type:
    an odd notification is dropped and never brings down the other connections."""
    try:
        raw = json.loads(payload)
        organization_id = UUID(str(raw.pop("organization_id")))
        kind = raw.pop("type")
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    if kind not in KINDS:
        return None
    return RealtimeEvent(organization_id, kind, raw)
