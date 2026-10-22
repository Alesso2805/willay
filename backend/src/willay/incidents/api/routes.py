"""Incidents REST API (VIG-19, VIG-26, VIG-35): list, view with its readings, acknowledge,
resolve and comment."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from willay.identity.api.dependencies import require
from willay.identity.domain.permissions import Permission
from willay.identity.domain.principal import Principal
from willay.incidents.application.lifecycle import (
    Actor,
    Incident,
    IncidentEvent,
    IncidentNotFoundError,
    acknowledge_incident,
    comment_on_incident,
    resolve_incident,
)
from willay.incidents.domain import chart
from willay.incidents.domain.comments import MAX_COMMENT_LENGTH
from willay.incidents.domain.lifecycle import (
    IncidentStatus,
    InvalidTransitionError,
    Resolution,
)
from willay.incidents.domain.severity import Severity
from willay.incidents.infrastructure.incident_readings import SqlIncidentReadings
from willay.incidents.infrastructure.incidents_repository import SqlIncidentRepository
from willay.shared.errors import ErrorCode, Term
from willay.shared.web import ApiError, ClockDep, DbConnection

router = APIRouter(prefix="/v1/incidents", tags=["incidents"])

CanView = Annotated[Principal, Depends(require(Permission.VIEW))]
CanAcknowledge = Annotated[Principal, Depends(require(Permission.ACKNOWLEDGE_INCIDENTS))]
CanResolve = Annotated[Principal, Depends(require(Permission.RESOLVE_INCIDENTS))]

_NOT_FOUND = ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.INCIDENT_NOT_FOUND)
# The dashboard shows the 409 detail verbatim: the status and action as translated words
# (VIG-40), not the internal values.
_TRANSITION_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"description": "Not found"},
    409: {"description": "Invalid transition for the current status"},
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
    actor_name: str | None = Field(description="The user or contact who acted; null for the system")
    contact_name: str | None = Field(
        description="For alert events, the recipient's name (never their email or chat)"
    )
    payload: dict[str, Any]


class IncidentDetailOut(IncidentOut):
    timeline: list[IncidentEventOut]


class ReadingOut(BaseModel):
    measured_at: datetime
    value: float


class ThresholdOut(BaseModel):
    operator: str = Field(description="gt, ge, lt or le")
    value: float


class IncidentReadingsOut(BaseModel):
    station_code: str | None
    unit: str | None
    window_start: datetime
    window_end: datetime
    source: Literal["readings", "evidence"] = Field(
        description="evidence: the readings expired, so these are the copy kept in the opened "
        "event (the ones that fired the rule)"
    )
    readings: list[ReadingOut]
    threshold: ThresholdOut | None = Field(description="A threshold rule's boundary, to draw")


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Surrounding spaces do not count: a comment of only spaces is empty (422).
    text: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_COMMENT_LENGTH),
    ]


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: Resolution


@router.get("", summary="The organization's incidents, most recent first")
async def list_incidents(
    principal: CanView,
    conn: DbConnection,
    status_: Annotated[
        list[IncidentStatus] | None,
        Query(alias="status", description="filter by status (repeatable)"),
    ] = None,
    severity: Annotated[
        list[Severity] | None, Query(description="filter by severity (repeatable)")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[IncidentOut]:
    incidents = await SqlIncidentRepository(conn).recent(
        principal.organization_id, status_ or [], severity or [], limit
    )
    return [_out(incident) for incident in incidents]


@router.get(
    "/{incident_id}",
    summary="An incident with its timeline",
    responses={404: {"description": "Not found"}},
)
async def get_incident(
    incident_id: UUID, principal: CanView, conn: DbConnection
) -> IncidentDetailOut:
    repository = SqlIncidentRepository(conn)
    incident = await repository.get(principal.organization_id, incident_id)
    if incident is None:
        raise _NOT_FOUND
    return _detail(incident, await repository.timeline(incident_id))


@router.get(
    "/{incident_id}/readings",
    summary="The readings around an incident's opening, for its chart",
    responses={404: {"description": "Not found"}},
)
async def get_incident_readings(
    incident_id: UUID, principal: CanView, conn: DbConnection, clock: ClockDep
) -> IncidentReadingsOut:
    incident = await SqlIncidentRepository(conn).get(principal.organization_id, incident_id)
    if incident is None:
        raise _NOT_FOUND
    readings = SqlIncidentReadings(conn)
    start, end = chart.readings_window(incident.opened_at, clock.now())
    opened = await readings.opened_payload(incident_id)
    station = None
    stored: list[chart.Point] = []
    if incident.station_id is not None:
        station = await readings.station(principal.organization_id, incident.station_id)
        stored = await readings.window(principal.organization_id, incident.station_id, start, end)
    source, points = chart.series(stored, chart.evidence(opened))
    line = chart.threshold(opened)
    return IncidentReadingsOut(
        station_code=station.code if station else None,
        unit=station.unit if station else None,
        window_start=start,
        window_end=end,
        source=source,
        readings=[ReadingOut(measured_at=p.measured_at, value=p.value) for p in points],
        threshold=ThresholdOut(operator=line.operator, value=line.value) if line else None,
    )


@router.post(
    "/{incident_id}/acknowledge",
    summary="Acknowledge an open incident",
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
    summary="Resolve an incident (resolved or false alarm), acknowledged or not",
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


@router.post(
    "/{incident_id}/comments",
    status_code=status.HTTP_201_CREATED,
    summary="Comment on an incident (also once resolved)",
    responses={404: {"description": "Not found"}},
)
async def comment_incident(
    incident_id: UUID,
    body: CommentIn,
    principal: CanAcknowledge,
    conn: DbConnection,
    clock: ClockDep,
) -> IncidentEventOut:
    incidents = SqlIncidentRepository(conn)
    try:
        event_id = await comment_on_incident(
            _actor(principal), incident_id, body.text, incidents=incidents, clock=clock
        )
    except IncidentNotFoundError as exc:
        raise _NOT_FOUND from exc
    # Read back through the timeline, so the answer carries the author's name like the rest.
    created = next(e for e in await incidents.timeline(incident_id) if e.id == event_id)
    return _event_out(created)


def _actor(principal: Principal) -> Actor:
    return Actor(principal.organization_id, principal.user_id)


def _conflict(exc: InvalidTransitionError) -> ApiError:
    return ApiError(
        status.HTTP_409_CONFLICT,
        ErrorCode.INCIDENT_TRANSITION,
        status=Term(f"incident_status.{exc.current.value}"),
        action=Term(f"incident_action.{exc.transition.value}"),
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
        timeline=[_event_out(e) for e in timeline],
    )


def _event_out(e: IncidentEvent) -> IncidentEventOut:
    return IncidentEventOut(
        id=e.id,
        occurred_at=e.occurred_at,
        event_type=e.event_type,
        actor_type=e.actor_type,
        actor_id=e.actor_id,
        actor_name=e.actor_name,
        contact_name=e.contact_name,
        payload=dict(e.payload),
    )
