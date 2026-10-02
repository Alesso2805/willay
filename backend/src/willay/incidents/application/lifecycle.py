"""List, acknowledge and resolve incidents (VIG-19), always scoped to the actor's organization
(another tenant's incident is a 404, not a 403).

Each transition locks the incident FOR UPDATE in the request transaction, so a concurrent
operator waits, sees the new status and gets a 409 instead of overwriting it. Both platform
users and account-less contacts (alert link, VIG-23) can acknowledge.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from willay.incidents.domain.lifecycle import (
    IncidentStatus,
    Resolution,
    Transition,
    ensure_allowed,
)
from willay.incidents.domain.severity import Severity
from willay.shared.clock import Clock


@dataclass(frozen=True)
class Actor:
    """A platform user, authenticated with their JWT."""

    organization_id: UUID  # the tenant: never taken from the request body
    user_id: UUID

    @property
    def actor_type(self) -> str:
        return "user"

    @property
    def actor_id(self) -> UUID:
        return self.user_id


@dataclass(frozen=True)
class ContactActor:
    """A contact acknowledging from their alert link (they have no account)."""

    organization_id: UUID  # taken from the alert, since there is no session
    contact_id: UUID

    @property
    def actor_type(self) -> str:
        return "contact"

    @property
    def actor_id(self) -> UUID:
        return self.contact_id


EventActor = Actor | ContactActor


class IncidentNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class Incident:
    id: UUID
    zone_id: UUID
    zone_name: str
    station_id: UUID | None
    station_code: str | None
    rule_id: UUID
    rule_type: str
    severity: str
    status: IncidentStatus
    current_level: int
    trigger_value: float | None
    opened_at: datetime
    escalation_exhausted_at: datetime | None
    acknowledged_at: datetime | None
    acknowledged_by_user_id: UUID | None
    acknowledged_by_contact_id: UUID | None
    resolved_at: datetime | None
    resolution: Resolution | None


@dataclass(frozen=True)
class IncidentEvent:
    id: int
    occurred_at: datetime
    event_type: str
    actor_type: str
    actor_id: UUID | None
    payload: Mapping[str, Any]


class IncidentRepository(Protocol):
    async def recent(
        self,
        organization_id: UUID,
        statuses: Sequence[IncidentStatus],
        severities: Sequence[Severity],
        limit: int,
    ) -> list[Incident]:
        """Most recent first; an empty `statuses` or `severities` means all."""
        ...

    async def get(self, organization_id: UUID, incident_id: UUID) -> Incident | None: ...

    async def timeline(self, incident_id: UUID) -> list[IncidentEvent]:
        """Events in chronological order."""
        ...

    async def lock_status(self, organization_id: UUID, incident_id: UUID) -> IncidentStatus | None:
        """Current status, locking the incident until the end of the transaction."""
        ...

    async def acknowledge(self, incident_id: UUID, actor: EventActor, now: datetime) -> None: ...

    async def resolve(self, incident_id: UUID, resolution: Resolution, now: datetime) -> None: ...

    async def add_event(
        self,
        incident_id: UUID,
        actor: EventActor,
        event_type: str,
        payload: Mapping[str, Any],
        now: datetime,
    ) -> None: ...


async def acknowledge_incident(
    actor: Actor, incident_id: UUID, *, incidents: IncidentRepository, clock: Clock
) -> Incident:
    current = await _lock(actor, incident_id, incidents)
    ensure_allowed(Transition.ACKNOWLEDGE, current)
    now = clock.now()
    await incidents.acknowledge(incident_id, actor, now)
    await incidents.add_event(incident_id, actor, "acknowledged", {}, now)
    return await _reload(actor, incident_id, incidents)


async def acknowledge_as_contact(
    actor: ContactActor, incident_id: UUID, *, incidents: IncidentRepository, clock: Clock
) -> IncidentStatus:
    """Acknowledges the incident if it is still open and returns the status it had.

    Unlike the API, it does not raise if someone got there first or it was already
    resolved: the contact made no mistake, they were just late, and the page explains it.
    """
    current = await _lock(actor, incident_id, incidents)
    if current is IncidentStatus.OPEN:
        now = clock.now()
        await incidents.acknowledge(incident_id, actor, now)
        await incidents.add_event(incident_id, actor, "acknowledged", {}, now)
    return current


async def resolve_incident(
    actor: Actor,
    incident_id: UUID,
    resolution: Resolution,
    *,
    incidents: IncidentRepository,
    clock: Clock,
) -> Incident:
    current = await _lock(actor, incident_id, incidents)
    ensure_allowed(Transition.RESOLVE, current)
    now = clock.now()
    await incidents.resolve(incident_id, resolution, now)
    payload = {"resolution": resolution.value, "previous_status": current.value}
    await incidents.add_event(incident_id, actor, "resolved", payload, now)
    return await _reload(actor, incident_id, incidents)


async def _lock(
    actor: EventActor, incident_id: UUID, incidents: IncidentRepository
) -> IncidentStatus:
    current = await incidents.lock_status(actor.organization_id, incident_id)
    if current is None:
        raise IncidentNotFoundError(incident_id)
    return current


async def _reload(actor: Actor, incident_id: UUID, incidents: IncidentRepository) -> Incident:
    incident = await incidents.get(actor.organization_id, incident_id)
    if incident is None:  # impossible in the same transaction; incidents are never deleted
        raise IncidentNotFoundError(incident_id)
    return incident
