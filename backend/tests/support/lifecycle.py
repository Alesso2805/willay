"""In-memory IncidentRepository for unit tests: a single incident."""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from willay.incidents.application.lifecycle import (
    Actor,
    EventActor,
    Incident,
    IncidentEvent,
)
from willay.incidents.domain.lifecycle import IncidentStatus, Resolution
from willay.incidents.domain.severity import Severity

T0 = datetime(2026, 11, 20, 14, 0, tzinfo=UTC)
OPEN, ACK, RESOLVED = IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED, IncidentStatus.RESOLVED


class FakeIncidentRepository:
    def __init__(self, organization_id: UUID, status: IncidentStatus = OPEN) -> None:
        self.incident = Incident(
            id=uuid4(),
            zone_id=uuid4(),
            zone_name="Chosica",
            station_id=uuid4(),
            station_code="RIM-CHA-01",
            rule_id=uuid4(),
            rule_type="rate_of_change",
            severity="critical",
            status=status,
            current_level=1,
            trigger_value=34.2,
            opened_at=T0,
            escalation_exhausted_at=None,
            acknowledged_at=None,
            acknowledged_by_user_id=None,
            acknowledged_by_contact_id=None,
            resolved_at=None,
            resolution=None,
        )
        self.organization_id = organization_id
        self.events: list[tuple[str, UUID, Mapping[str, Any]]] = []

    def _mine(self, organization_id: UUID, incident_id: UUID) -> bool:
        return organization_id == self.organization_id and incident_id == self.incident.id

    async def recent(
        self,
        organization_id: UUID,
        statuses: Sequence[IncidentStatus],
        severities: Sequence[Severity],
        limit: int,
    ) -> list[Incident]:
        return [self.incident]

    async def get(self, organization_id: UUID, incident_id: UUID) -> Incident | None:
        return self.incident if self._mine(organization_id, incident_id) else None

    async def timeline(self, incident_id: UUID) -> list[IncidentEvent]:
        return []

    async def lock_status(self, organization_id: UUID, incident_id: UUID) -> IncidentStatus | None:
        return self.incident.status if self._mine(organization_id, incident_id) else None

    async def acknowledge(self, incident_id: UUID, actor: EventActor, now: datetime) -> None:
        by_user = isinstance(actor, Actor)
        self.incident = replace(
            self.incident,
            status=ACK,
            acknowledged_at=now,
            acknowledged_by_user_id=actor.actor_id if by_user else None,
            acknowledged_by_contact_id=None if by_user else actor.actor_id,
        )

    async def resolve(self, incident_id: UUID, resolution: Resolution, now: datetime) -> None:
        self.incident = replace(
            self.incident, status=RESOLVED, resolved_at=now, resolution=resolution
        )

    async def add_event(
        self,
        incident_id: UUID,
        actor: EventActor,
        event_type: str,
        payload: Mapping[str, Any],
        now: datetime,
    ) -> None:
        self.events.append((event_type, actor.actor_id, payload))
