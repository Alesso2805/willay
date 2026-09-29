"""API REST de incidentes (VIG-19): consultar, confirmar y resolver."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from vigia.identity.api.dependencies import require
from vigia.identity.domain.permissions import Permission
from vigia.identity.domain.principal import Principal
from vigia.incidents.application.lifecycle import (
    Actor,
    Incident,
    IncidentEvent,
    IncidentNotFoundError,
    acknowledge_incident,
    resolve_incident,
)
from vigia.incidents.domain.lifecycle import (
    IncidentStatus,
    InvalidTransitionError,
    Resolution,
    Transition,
)
from vigia.incidents.infrastructure.incidents_repository import SqlIncidentRepository
from vigia.shared.web import ClockDep, DbConnection

router = APIRouter(prefix="/v1/incidents", tags=["incidents"])

CanView = Annotated[Principal, Depends(require(Permission.VIEW))]
CanAcknowledge = Annotated[Principal, Depends(require(Permission.ACKNOWLEDGE_INCIDENTS))]
CanResolve = Annotated[Principal, Depends(require(Permission.RESOLVE_INCIDENTS))]

_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="Incidente no encontrado")
# El panel muestra el detalle del 409 tal cual: en español, no los valores internos.
_STATUS_LABEL = {
    IncidentStatus.OPEN: "abierto",
    IncidentStatus.ACKNOWLEDGED: "confirmado",
    IncidentStatus.RESOLVED: "resuelto",
}
_TRANSITION_LABEL = {Transition.ACKNOWLEDGE: "confirmar", Transition.RESOLVE: "resolver"}
_TRANSITION_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"description": "No existe"},
    409: {"description": "Transición inválida para el estado actual"},
}


class IncidentOut(BaseModel):
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


class IncidentEventOut(BaseModel):
    id: int
    occurred_at: datetime
    event_type: str
    actor_type: str
    actor_id: UUID | None
    payload: dict[str, Any]


class IncidentDetailOut(IncidentOut):
    timeline: list[IncidentEventOut]


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: Resolution


@router.get("", summary="Incidentes de la organización, los más recientes primero")
async def list_incidents(
    principal: CanView,
    conn: DbConnection,
    status_: Annotated[
        list[IncidentStatus] | None,
        Query(alias="status", description="filtrar por estado (se puede repetir)"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[IncidentOut]:
    incidents = await SqlIncidentRepository(conn).recent(
        principal.organization_id, status_ or [], limit
    )
    return [_out(incident) for incident in incidents]


@router.get(
    "/{incident_id}",
    summary="Un incidente con su línea de tiempo",
    responses={404: {"description": "No existe"}},
)
async def get_incident(
    incident_id: UUID, principal: CanView, conn: DbConnection
) -> IncidentDetailOut:
    repository = SqlIncidentRepository(conn)
    incident = await repository.get(principal.organization_id, incident_id)
    if incident is None:
        raise _NOT_FOUND
    return _detail(incident, await repository.timeline(incident_id))


@router.post(
    "/{incident_id}/acknowledge",
    summary="Confirmar un incidente abierto",
    responses=_TRANSITION_RESPONSES,
)
async def post_acknowledge(
    incident_id: UUID, principal: CanAcknowledge, conn: DbConnection, clock: ClockDep
) -> IncidentOut:
    try:
        incident = await acknowledge_incident(
            _actor(principal), incident_id, incidents=SqlIncidentRepository(conn), clock=clock
        )
    except IncidentNotFoundError as exc:
        raise _NOT_FOUND from exc
    except InvalidTransitionError as exc:
        raise _conflict(exc) from exc
    return _out(incident)


@router.post(
    "/{incident_id}/resolve",
    summary="Resolver un incidente (resuelto o falsa alarma), confirmado o no",
    responses=_TRANSITION_RESPONSES,
)
async def post_resolve(
    incident_id: UUID,
    body: ResolveIn,
    principal: CanResolve,
    conn: DbConnection,
    clock: ClockDep,
) -> IncidentOut:
    try:
        incident = await resolve_incident(
            _actor(principal),
            incident_id,
            body.resolution,
            incidents=SqlIncidentRepository(conn),
            clock=clock,
        )
    except IncidentNotFoundError as exc:
        raise _NOT_FOUND from exc
    except InvalidTransitionError as exc:
        raise _conflict(exc) from exc
    return _out(incident)


def _actor(principal: Principal) -> Actor:
    return Actor(principal.organization_id, principal.user_id)


def _conflict(exc: InvalidTransitionError) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        detail=(
            f"El incidente ya está {_STATUS_LABEL[exc.current]}: "
            f"no se puede {_TRANSITION_LABEL[exc.transition]}."
        ),
    )


def _out(incident: Incident) -> IncidentOut:
    return IncidentOut(
        id=incident.id,
        zone_id=incident.zone_id,
        zone_name=incident.zone_name,
        station_id=incident.station_id,
        station_code=incident.station_code,
        rule_id=incident.rule_id,
        rule_type=incident.rule_type,
        severity=incident.severity,
        status=incident.status,
        current_level=incident.current_level,
        trigger_value=incident.trigger_value,
        opened_at=incident.opened_at,
        escalation_exhausted_at=incident.escalation_exhausted_at,
        acknowledged_at=incident.acknowledged_at,
        acknowledged_by_user_id=incident.acknowledged_by_user_id,
        acknowledged_by_contact_id=incident.acknowledged_by_contact_id,
        resolved_at=incident.resolved_at,
        resolution=incident.resolution,
    )


def _detail(incident: Incident, timeline: list[IncidentEvent]) -> IncidentDetailOut:
    return IncidentDetailOut(
        **_out(incident).model_dump(),
        timeline=[
            IncidentEventOut(
                id=e.id,
                occurred_at=e.occurred_at,
                event_type=e.event_type,
                actor_type=e.actor_type,
                actor_id=e.actor_id,
                payload=dict(e.payload),
            )
            for e in timeline
        ],
    )
