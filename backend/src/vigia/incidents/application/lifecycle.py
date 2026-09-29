"""Consultar, confirmar y resolver incidentes (VIG-19). Todo filtra por la organización
del actor: un incidente de otra organización no existe para él (404, no 403).

Cada transición bloquea el incidente (FOR UPDATE) en la transacción de la petición, el
dominio decide si es válida y el cambio y su evento se escriben juntos. Si dos
operadores actúan a la vez, el segundo espera al primero, ve el estado nuevo y recibe
una transición inválida (409) en lugar de pisarlo.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from vigia.incidents.domain.lifecycle import (
    IncidentStatus,
    Resolution,
    Transition,
    ensure_allowed,
)
from vigia.shared.clock import Clock


@dataclass(frozen=True)
class Actor:
    organization_id: UUID  # el tenant: nunca sale del cuerpo de la petición
    user_id: UUID


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
        self, organization_id: UUID, statuses: Sequence[IncidentStatus], limit: int
    ) -> list[Incident]:
        """Los más recientes primero; `statuses` vacío significa todos."""
        ...

    async def get(self, organization_id: UUID, incident_id: UUID) -> Incident | None: ...

    async def timeline(self, incident_id: UUID) -> list[IncidentEvent]:
        """Eventos en orden cronológico."""
        ...

    async def lock_status(self, organization_id: UUID, incident_id: UUID) -> IncidentStatus | None:
        """Estado actual, bloqueando el incidente hasta el final de la transacción."""
        ...

    async def acknowledge(self, incident_id: UUID, user_id: UUID, now: datetime) -> None: ...

    async def resolve(self, incident_id: UUID, resolution: Resolution, now: datetime) -> None: ...

    async def add_event(
        self,
        incident_id: UUID,
        actor: Actor,
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
    await incidents.acknowledge(incident_id, actor.user_id, now)
    await incidents.add_event(incident_id, actor, "acknowledged", {}, now)
    return await _reload(actor, incident_id, incidents)


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


async def _lock(actor: Actor, incident_id: UUID, incidents: IncidentRepository) -> IncidentStatus:
    current = await incidents.lock_status(actor.organization_id, incident_id)
    if current is None:
        raise IncidentNotFoundError(incident_id)
    return current


async def _reload(actor: Actor, incident_id: UUID, incidents: IncidentRepository) -> Incident:
    incident = await incidents.get(actor.organization_id, incident_id)
    if incident is None:  # imposible dentro de la misma transacción; no se borran incidentes
        raise IncidentNotFoundError(incident_id)
    return incident
