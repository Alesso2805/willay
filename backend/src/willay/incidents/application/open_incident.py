"""What happens to an incident when a rule fires (evaluator and silence worker).

- No active incident for the cause: open one with its `opened` event.
- Cause resolved less than `cooldown_s` ago: open nothing (the reading is already stored).
- Already active: add `reading_added` only if the reading worsens the trigger value.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from willay.incidents.domain.incidents import EvidenceReading, Worsening


@dataclass(frozen=True)
class Trigger:
    """What a rule found: enough to open the incident and document why."""

    organization_id: UUID
    zone_id: UUID
    rule_id: UUID
    rule_type: str
    rule_params: Mapping[str, Any]
    severity: str
    station_id: UUID
    # The reading with the trigger value; None for a silent station with no last value.
    trigger_reading: EvidenceReading | None
    dedup_key: str
    cooldown_s: int
    # Copy of the readings that fired the rule: survives the 180-day retention.
    evidence: tuple[EvidenceReading, ...]
    # Rule-type-specific context, e.g. the last heartbeat of a silent station.
    details: Mapping[str, Any] = field(default_factory=dict)
    # None if readings cannot worsen the rule (silence).
    worsening: Worsening | None = None

    @property
    def trigger_value(self) -> float | None:
        return self.trigger_reading.value if self.trigger_reading is not None else None


class OpenStatus(StrEnum):
    OPENED = "opened"
    ACTIVE = "active"  # one with the same cause was already active
    COOLING_DOWN = "cooling_down"  # the cause was resolved less than cooldown_s ago


@dataclass(frozen=True)
class OpenResult:
    status: OpenStatus
    incident_id: UUID | None  # the opened or active one; None while cooling down


class IncidentStore(Protocol):
    async def open(self, tx: AsyncConnection, trigger: Trigger, now: datetime) -> OpenResult:
        """Opens the incident and its `opened` event in `tx`, unless one with the same cause
        is active or the cause is cooling down."""
        ...

    async def worst_value(self, tx: AsyncConnection, incident_id: UUID) -> float | None:
        """The worst recorded value (the trigger or the last `reading_added`). Locks the
        incident until the end of `tx` so two evaluators cannot worsen it at once."""
        ...

    async def add_reading(
        self,
        tx: AsyncConnection,
        incident_id: UUID,
        organization_id: UUID,
        reading: EvidenceReading,
        now: datetime,
    ) -> None:
        """Records a `reading_added` event with the reading."""
        ...


class TriggerOutcome(StrEnum):
    OPENED = "opened"
    READING_ADDED = "reading_added"
    UNCHANGED = "unchanged"  # active, and the reading does not worsen it
    COOLING_DOWN = "cooling_down"


@dataclass(frozen=True)
class Recorded:
    outcome: TriggerOutcome
    incident_id: UUID | None


async def record_trigger(
    store: IncidentStore, tx: AsyncConnection, trigger: Trigger, now: datetime
) -> Recorded:
    result = await store.open(tx, trigger, now)
    if result.status is OpenStatus.OPENED:
        return Recorded(TriggerOutcome.OPENED, result.incident_id)
    if result.status is OpenStatus.COOLING_DOWN or result.incident_id is None:
        return Recorded(TriggerOutcome.COOLING_DOWN, None)

    incident_id, reading, worsening = result.incident_id, trigger.trigger_reading, trigger.worsening
    if reading is None or worsening is None:
        return Recorded(TriggerOutcome.UNCHANGED, incident_id)
    worst = await store.worst_value(tx, incident_id)
    if worst is not None and not worsening.is_worse(reading.value, worst):
        return Recorded(TriggerOutcome.UNCHANGED, incident_id)
    await store.add_reading(tx, incident_id, trigger.organization_id, reading, now)
    return Recorded(TriggerOutcome.READING_ADDED, incident_id)
