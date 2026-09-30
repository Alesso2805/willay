"""API REST de políticas de escalamiento (VIG-24).

Leer: cualquier rol (el formulario de reglas, VIG-27, elige una política; no hay datos
personales, solo grupos). Crear, editar y borrar: solo admin (SPEC: Permisos por rol).
Los niveles se envían como lista: su orden es su posición.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict

from vigia.alerts.application.policies import (
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
from vigia.alerts.domain.alerts import Channel
from vigia.alerts.domain.policies import InvalidPolicyError, LevelData, PolicyData, Target
from vigia.alerts.infrastructure.policies_repository import SqlPolicyRepository
from vigia.identity.api.dependencies import require
from vigia.identity.domain.permissions import Permission
from vigia.identity.domain.principal import Principal
from vigia.shared.audit import SqlAuditLog
from vigia.shared.web import ClockDep, DbConnection

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


@router.get("", summary="Políticas de escalamiento de la organización")
async def list_policies(principal: CanView, conn: DbConnection) -> list[PolicyOut]:
    policies = await SqlPolicyRepository(conn).all_of(principal.organization_id)
    return [_out(policy) for policy in policies]


@router.get("/{policy_id}", summary="Una política", responses={404: {"description": "No existe"}})
async def get_policy(policy_id: UUID, principal: CanView, conn: DbConnection) -> PolicyOut:
    policy = await SqlPolicyRepository(conn).get(principal.organization_id, policy_id)
    if policy is None:
        raise _NOT_FOUND
    return _out(policy)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Crear una política",
    responses={
        409: {"description": "Ya hay una política con ese nombre"},
        422: {"description": "Niveles inválidos o grupos que no son de la organización"},
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
    summary="Reemplazar una política (nombre y niveles); aplica a los incidentes en curso",
    responses={
        404: {"description": "No existe"},
        409: {"description": "Ya hay una política con ese nombre"},
        422: {"description": "Niveles inválidos o grupos que no son de la organización"},
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
    summary="Borrar una política que ninguna regla usa",
    responses={404: {"description": "No existe"}, 409: {"description": "Alguna regla la usa"}},
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
    # Mismo formato que los 422 de validación de FastAPI, para que el panel los trate igual.
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
