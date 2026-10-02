"""Rules REST API (VIG-27).

Everyone with `view` reads them (SPEC); operator and admin manage them (`rules:manage`). The
body says the rule's type and its params are validated for that type: Pydantic checks their
shape here, and the domain parses them with the evaluator's own functions before storing.
DELETE deactivates; a PUT with `is_active: true` reactivates. The type never changes.
"""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from willay.identity.api.dependencies import require
from willay.identity.domain.permissions import Permission
from willay.identity.domain.principal import Principal
from willay.incidents.domain.severity import Severity
from willay.rules.application.actor import Actor
from willay.rules.application.preview import Preview, preview_rule
from willay.rules.application.rules import (
    Rule,
    RuleNotFoundError,
    create_rule,
    deactivate_rule,
    update_rule,
)
from willay.rules.domain.rate_of_change import MAX_WINDOW_MINUTES, Direction
from willay.rules.domain.rules import MAX_COOLDOWN_S, InvalidRuleError, RuleData, RuleType
from willay.rules.domain.threshold import MAX_CONSECUTIVE, Operator
from willay.rules.infrastructure.rules_repository import SqlRuleAdminRepository
from willay.rules.infrastructure.sql_preview import SqlPreviewRepository
from willay.shared.audit import SqlAuditLog
from willay.shared.web import ClockDep, DbConnection

router = APIRouter(prefix="/v1/rules", tags=["rules"])

CanView = Annotated[Principal, Depends(require(Permission.VIEW))]
CanManage = Annotated[Principal, Depends(require(Permission.MANAGE_RULES))]

_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="Regla no encontrada")
_WRITE_RESPONSES: dict[int | str, dict[str, str]] = {
    422: {"description": "Invalid params for the type, or a zone, station or policy outside "
          "the organization"},
}  # fmt: skip


class ThresholdParamsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator: Operator
    value: Annotated[float, Field(allow_inf_nan=False)]
    consecutive: Annotated[int, Field(ge=1, le=MAX_CONSECUTIVE)]


class RateOfChangeParamsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: Direction
    delta: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    window_minutes: Annotated[int, Field(ge=1, le=MAX_WINDOW_MINUTES)]


class SilenceParamsIn(BaseModel):
    """K lives in each station's silence_multiplier (SPEC): a silence rule has no params."""

    model_config = ConfigDict(extra="forbid")


class _RuleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zone_id: UUID
    station_id: UUID | None = Field(
        default=None, description="None: every station of the zone (silence rules only)"
    )
    severity: Severity
    escalation_policy_id: UUID
    cooldown_s: Annotated[int, Field(ge=0, le=MAX_COOLDOWN_S)]
    is_active: bool = True


class ThresholdRuleIn(_RuleBody):
    type: Literal[RuleType.THRESHOLD]
    params: ThresholdParamsIn


class RateOfChangeRuleIn(_RuleBody):
    type: Literal[RuleType.RATE_OF_CHANGE]
    params: RateOfChangeParamsIn


class SilenceRuleIn(_RuleBody):
    type: Literal[RuleType.SILENCE]
    params: SilenceParamsIn = SilenceParamsIn()


# The type picks which params model applies, so a 422 points at the exact field.
RuleIn = Annotated[
    ThresholdRuleIn | RateOfChangeRuleIn | SilenceRuleIn,
    Body(discriminator="type"),
]


class _PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zone_id: UUID
    station_id: UUID | None = None


class ThresholdPreviewIn(_PreviewBody):
    type: Literal[RuleType.THRESHOLD]
    params: ThresholdParamsIn


class RateOfChangePreviewIn(_PreviewBody):
    type: Literal[RuleType.RATE_OF_CHANGE]
    params: RateOfChangeParamsIn


class SilencePreviewIn(_PreviewBody):
    type: Literal[RuleType.SILENCE]
    params: SilenceParamsIn = SilenceParamsIn()


PreviewIn = Annotated[
    ThresholdPreviewIn | RateOfChangePreviewIn | SilencePreviewIn,
    Body(discriminator="type"),
]


class RefOut(BaseModel):
    id: UUID
    name: str


class StationRefOut(BaseModel):
    id: UUID
    code: str
    name: str
    unit: str = Field(description="The unit of the params' value and delta")


class RuleOut(BaseModel):
    id: UUID
    type: RuleType
    zone: RefOut
    station: StationRefOut | None
    params: dict[str, Any] = Field(description="Per type, as in the request")
    severity: Severity
    escalation_policy: RefOut
    cooldown_s: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PointOut(BaseModel):
    measured_at: datetime
    value: float


class FiringOut(BaseModel):
    at: datetime = Field(description="When the incident would have opened")
    value: float | None = Field(description="The reading that fired it; None for silence")


class StationPreviewOut(BaseModel):
    station: StationRefOut
    readings: list[PointOut] = Field(description="The period's `ok` readings, oldest first")
    firings: list[FiringOut]
    truncated: bool = Field(description="More readings than the limit: the oldest were left out")


class PreviewOut(BaseModel):
    since: datetime
    until: datetime
    stations: list[StationPreviewOut]


@router.get("", summary="The organization's rules, by zone")
async def list_rules(
    principal: CanView,
    conn: DbConnection,
    include_inactive: Annotated[bool, Query(description="include deactivated ones")] = False,
) -> list[RuleOut]:
    rules = await SqlRuleAdminRepository(conn).all_of(
        principal.organization_id, include_inactive=include_inactive
    )
    return [_out(rule) for rule in rules]


@router.post(
    "/preview",
    summary="When a draft rule would have opened incidents over the last 24 h",
    responses={
        422: {"description": "Invalid params, or a zone or station outside the organization"}
    },
)
async def post_preview(
    body: PreviewIn, principal: CanManage, conn: DbConnection, clock: ClockDep
) -> PreviewOut:
    try:
        preview = await preview_rule(
            principal.organization_id, body.type, body.zone_id, body.station_id,
            body.params.model_dump(mode="json"), repository=SqlPreviewRepository(conn), clock=clock,
        )  # fmt: skip
    except InvalidRuleError as exc:
        raise _invalid(exc) from exc
    return _preview_out(preview)


@router.get("/{rule_id}", summary="A rule", responses={404: {"description": "Not found"}})
async def get_rule(rule_id: UUID, principal: CanView, conn: DbConnection) -> RuleOut:
    rule = await SqlRuleAdminRepository(conn).get(principal.organization_id, rule_id)
    if rule is None:
        raise _NOT_FOUND
    return _out(rule)


@router.post(
    "", status_code=status.HTTP_201_CREATED, summary="Create a rule", responses=_WRITE_RESPONSES
)
async def post_rule(
    body: RuleIn, principal: CanManage, conn: DbConnection, clock: ClockDep, response: Response
) -> RuleOut:
    try:
        rule = await create_rule(
            _actor(principal), body.type, _data(body), rules=SqlRuleAdminRepository(conn),
            audit=SqlAuditLog(conn), clock=clock,
        )  # fmt: skip
    except InvalidRuleError as exc:
        raise _invalid(exc) from exc
    response.headers["Location"] = f"/v1/rules/{rule.id}"
    return _out(rule)


@router.put(
    "/{rule_id}",
    summary="Replace a rule (its type never changes); applies from the next reading",
    responses={404: {"description": "Not found"}, **_WRITE_RESPONSES},
)
async def put_rule(
    rule_id: UUID, body: RuleIn, principal: CanManage, conn: DbConnection, clock: ClockDep
) -> RuleOut:
    try:
        rule = await update_rule(
            _actor(principal), rule_id, body.type, _data(body),
            rules=SqlRuleAdminRepository(conn), audit=SqlAuditLog(conn), clock=clock,
        )  # fmt: skip
    except RuleNotFoundError as exc:
        raise _NOT_FOUND from exc
    except InvalidRuleError as exc:
        raise _invalid(exc) from exc
    return _out(rule)


@router.delete(
    "/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a rule (incidents keep pointing to it)",
    responses={404: {"description": "Not found"}},
)
async def delete_rule(
    rule_id: UUID, principal: CanManage, conn: DbConnection, clock: ClockDep
) -> Response:
    try:
        await deactivate_rule(
            _actor(principal), rule_id, rules=SqlRuleAdminRepository(conn),
            audit=SqlAuditLog(conn), clock=clock,
        )  # fmt: skip
    except RuleNotFoundError as exc:
        raise _NOT_FOUND from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _actor(principal: Principal) -> Actor:
    return Actor(principal.organization_id, principal.user_id)


def _data(body: ThresholdRuleIn | RateOfChangeRuleIn | SilenceRuleIn) -> RuleData:
    return RuleData(
        zone_id=body.zone_id,
        station_id=body.station_id,
        params=body.params.model_dump(mode="json"),
        severity=body.severity,
        escalation_policy_id=body.escalation_policy_id,
        cooldown_s=body.cooldown_s,
        is_active=body.is_active,
    )


def _invalid(exc: InvalidRuleError) -> HTTPException:
    """The same shape as FastAPI's own validation errors, so the dashboard reads both alike."""
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[{"loc": ["body", exc.field], "msg": str(exc), "type": "value_error"}],
    )


def _preview_out(preview: Preview) -> PreviewOut:
    return PreviewOut(
        since=preview.since,
        until=preview.until,
        stations=[
            StationPreviewOut(
                station=StationRefOut(
                    id=p.station.id, code=p.station.code, name=p.station.name, unit=p.station.unit
                ),
                readings=[PointOut(measured_at=r.at, value=r.value) for r in p.readings],
                firings=[FiringOut(at=f.at, value=f.value) for f in p.firings],
                truncated=p.truncated,
            )
            for p in preview.stations
        ],
    )


def _out(rule: Rule) -> RuleOut:
    station = rule.station
    return RuleOut(
        id=rule.id,
        type=rule.type,
        zone=RefOut(id=rule.zone.id, name=rule.zone.name),
        station=(
            StationRefOut(id=station.id, code=station.code, name=station.name, unit=station.unit)
            if station is not None
            else None
        ),
        params=dict(rule.data.params),
        severity=rule.data.severity,
        escalation_policy=RefOut(id=rule.policy.id, name=rule.policy.name),
        cooldown_s=rule.data.cooldown_s,
        is_active=rule.data.is_active,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )
