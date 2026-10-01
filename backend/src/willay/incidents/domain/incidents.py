"""Incidents: cause (dedup_key), opening evidence and readings that worsen them.

One active incident per cause (SPEC): `rule_id:zone_id` for threshold and rate of change,
`rule_id:zone_id:station_id` for silence (one incident per silent station). While active, a
reading that still fires the rule is added (`reading_added`) only if it worsens the trigger
value, so the timeline shows how the event escalated without repeating every reading.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


def dedup_key(rule_id: UUID, zone_id: UUID, station_id: UUID | None = None) -> str:
    base = f"{rule_id}:{zone_id}"
    return f"{base}:{station_id}" if station_id is not None else base


@dataclass(frozen=True)
class EvidenceReading:
    measured_at: datetime
    value: float


class Worsening(StrEnum):
    """Direction in which a rule's trigger value gets worse."""

    HIGHER = "higher"
    LOWER = "lower"

    def is_worse(self, candidate: float, worst_so_far: float) -> bool:
        """Strict: matching the worst value does not worsen it (reprocessing a reading does
        not duplicate events)."""
        if self is Worsening.HIGHER:
            return candidate > worst_so_far
        return candidate < worst_so_far
