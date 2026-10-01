"""Escalation policies REST API (VIG-24).

Any role can read (the rules form, VIG-27, picks a policy; there is no personal data, only
groups). Only admin can create, edit and delete (SPEC: Permissions by role). Levels are sent
as a list: their order is their position.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict

from willay.alerts.application.policies import (
    Actor,
    DuplicatePolicyNameError,
    Policy,
    PolicyInUseError,
    PolicyNotFoundError,
    UnknownGroupsError,
    create_policy,
    delete_policy,
    update_policy,
)
from willay.alerts.domain.alerts import Channel
from willay.alerts.domain.policies import InvalidPolicyError, LevelData, PolicyData, Target
from willay.alerts.infrastructure.policies_repository import SqlPolicyRepository
from willay.identity.api.dependencies import require
from willay.identity.domain.permissions import Permission
from willay.identity.domain.principal import Principal
from willay.shared.audit import SqlAuditLog
from willay.shared.web import ClockDep, DbConnection

router = APIRouter(prefix="/v1/escalation-policies", tags=["alerts"])

CanView = Annotated[Principal, Depends(require(Permission.VIEW))]
CanManage = Annotated[Principal, Depends(require(Permission.MANAGE_POLICIES))]

_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="Política no encontrada")


class TargetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_group_id: UUID
    channel: Channel


class LevelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wait_s: int
    targets: list[TargetIn]


class PolicyIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str
    levels: list[LevelIn]


class TargetOut(BaseModel):
    contact_group_id: UUID
    contact_group_name: str
    channel: Channel


class LevelOut(BaseModel):
    level_order: int
    wait_s: int
    targets: list[TargetOut]


class PolicyOut(BaseModel):
    id: UUID
    name: str
    levels: list[LevelOut]
    created_at: datetime


@router.get("", summary="The organization's escalation policies")
async def list_policies(principal: CanView, conn: DbConnection) -> list[PolicyOut]:
    policies = await SqlPolicyRepository(conn).all_of(principal.organization_id)
    return [_out(policy) for policy in policies]


@router.get("/{policy_id}", summary="A policy", responses={404: {"description": "Not found"}})
async def get_policy(policy_id: UUID, principal: CanView, conn: DbConnection) -> PolicyOut:
    policy = await SqlPolicyRepository(conn).get(principal.organization_id, policy_id)
    if policy is None:
        raise _NOT_FOUND
    return _out(policy)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a policy",
    responses={
        409: {"description": "A policy with that name already exists"},
        422: {"description": "Invalid levels, or groups that do not belong to the organization"},
    },
)
async def post_policy(
    body: PolicyIn, principal: CanManage, conn: DbConnection, clock: ClockDep, response: Response
) -> PolicyOut:
    try:
        policy = await create_policy(
            _actor(principal),
            _data(body),
            policies=SqlPolicyRepository(conn),
            audit=SqlAuditLog(conn),
            clock=clock,
        )
    except (InvalidPolicyError, UnknownGroupsError, DuplicatePolicyNameError) as exc:
        raise _rejected(exc) from exc
    response.headers["Location"] = f"/v1/escalation-policies/{policy.id}"
    return _out(policy)


@router.put(
    "/{policy_id}",
    summary="Replace a policy (name and levels); applies to ongoing incidents",
    responses={
        404: {"description": "Not found"},
        409: {"description": "A policy with that name already exists"},
        422: {"description": "Invalid levels, or groups that do not belong to the organization"},
    },
)
async def put_policy(
    policy_id: UUID, body: PolicyIn, principal: CanManage, conn: DbConnection, clock: ClockDep
) -> PolicyOut:
    try:
        policy = await update_policy(
            _actor(principal),
            policy_id,
            _data(body),
            policies=SqlPolicyRepository(conn),
            audit=SqlAuditLog(conn),
            clock=clock,
        )
    except PolicyNotFoundError as exc:
        raise _NOT_FOUND from exc
    except (InvalidPolicyError, UnknownGroupsError, DuplicatePolicyNameError) as exc:
        raise _rejected(exc) from exc
    return _out(policy)


@router.delete(
    "/{policy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a policy that no rule uses",
    responses={404: {"description": "Not found"}, 409: {"description": "A rule uses it"}},
)
async def delete_policy_route(
    policy_id: UUID, principal: CanManage, conn: DbConnection, clock: ClockDep
) -> None:
    try:
        await delete_policy(
            _actor(principal),
            policy_id,
            policies=SqlPolicyRepository(conn),
            audit=SqlAuditLog(conn),
            clock=clock,
        )
    except PolicyNotFoundError as exc:
        raise _NOT_FOUND from exc
    except PolicyInUseError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Alguna regla usa esta política: cámbiala en esas reglas antes de borrarla.",
        ) from exc


def _actor(principal: Principal) -> Actor:
    return Actor(principal.organization_id, principal.user_id)


def _data(body: PolicyIn) -> PolicyData:
    return PolicyData(
        name=body.name,
        levels=tuple(
            LevelData(
                level.wait_s,
                tuple(Target(t.contact_group_id, t.channel) for t in level.targets),
            )
            for level in body.levels
        ),
    )


def _rejected(exc: Exception) -> HTTPException:
    if isinstance(exc, DuplicatePolicyNameError):
        return HTTPException(status.HTTP_409_CONFLICT, detail="Ya hay una política con ese nombre.")
    # Same shape as FastAPI's validation 422s, so the dashboard handles them the same way.
    if isinstance(exc, UnknownGroupsError):
        detail = [{"loc": ["body", "levels"], "msg": str(exc), "type": "unknown_contact_group"}]
    else:
        detail = [{"loc": ["body", "levels"], "msg": str(exc), "type": "invalid_policy"}]
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _out(policy: Policy) -> PolicyOut:
    return PolicyOut(
        id=policy.id,
        name=policy.name,
        created_at=policy.created_at,
        levels=[
            LevelOut(
                level_order=level.level_order,
                wait_s=level.wait_s,
                targets=[
                    TargetOut(
                        contact_group_id=t.contact_group_id,
                        contact_group_name=t.contact_group_name,
                        channel=t.channel,
                    )
                    for t in level.targets
                ],
            )
            for level in policy.levels
        ],
    )
