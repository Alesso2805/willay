"""Contact groups API (VIG-36): who each escalation level notifies.

Admin and operator read (members are contact data, which is theirs to see); only admin
writes, audited. The member list is sent whole on every edit. Each group says which policies
notify it, so the dashboard can explain beforehand why it cannot be deleted.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict

from willay.alerts.application.groups import (
    ContactGroup,
    DuplicateGroupNameError,
    GroupInUseError,
    GroupNotFoundError,
    Ref,
    create_group,
    delete_group,
    update_group,
)
from willay.alerts.application.policies import Actor
from willay.alerts.domain.groups import GroupData, InvalidGroupError
from willay.alerts.infrastructure.groups_repository import SqlGroupRepository
from willay.identity.api.dependencies import require
from willay.identity.domain.permissions import Permission
from willay.identity.domain.principal import Principal
from willay.shared.audit import SqlAuditLog
from willay.shared.errors import ErrorCode, Names
from willay.shared.web import ApiError, ClockDep, DbConnection, invalid_field

router = APIRouter(prefix="/v1/contact-groups", tags=["alerts"])

CanView = Annotated[Principal, Depends(require(Permission.VIEW_CONTACT_DETAILS))]
CanManage = Annotated[Principal, Depends(require(Permission.MANAGE_CONTACTS))]

_NOT_FOUND = ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.GROUP_NOT_FOUND)
_DUPLICATE = ApiError(status.HTTP_409_CONFLICT, ErrorCode.GROUP_NAME_TAKEN)
_WRITE_RESPONSES: dict[int | str, dict[str, str]] = {
    409: {"description": "A group with that name already exists"},
    422: {"description": "Invalid name, or a zone or contacts outside the organization"},
}


class GroupIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str
    zone_id: UUID | None = None
    member_ids: list[UUID] = []

    @property
    def data(self) -> GroupData:
        return GroupData(self.name, self.zone_id, frozenset(self.member_ids))


class RefOut(BaseModel):
    id: UUID
    name: str


class GroupOut(BaseModel):
    id: UUID
    name: str
    zone: RefOut | None
    members: list[RefOut]
    policies: list[RefOut]


@router.get("", summary="The organization's contact groups, by name")
async def list_groups(principal: CanView, conn: DbConnection) -> list[GroupOut]:
    groups = await SqlGroupRepository(conn).all_of(principal.organization_id)
    return [_out(group) for group in groups]


@router.get("/{group_id}", summary="A contact group", responses={404: {"description": "Not found"}})
async def get_group(group_id: UUID, principal: CanView, conn: DbConnection) -> GroupOut:
    group = await SqlGroupRepository(conn).get(principal.organization_id, group_id)
    if group is None:
        raise _NOT_FOUND
    return _out(group)


@router.post(
    "", status_code=status.HTTP_201_CREATED, summary="Create a group", responses=_WRITE_RESPONSES
)
async def post_group(
    body: GroupIn, principal: CanManage, conn: DbConnection, clock: ClockDep
) -> GroupOut:
    try:
        group = await create_group(
            _actor(principal), body.data, groups=SqlGroupRepository(conn),
            audit=SqlAuditLog(conn), clock=clock,
        )  # fmt: skip
    except InvalidGroupError as exc:
        raise _invalid(exc) from exc
    except DuplicateGroupNameError as exc:
        raise _DUPLICATE from exc
    return _out(group)


@router.put(
    "/{group_id}",
    summary="Replace a group's name, zone and members",
    responses={404: {"description": "Not found"}, **_WRITE_RESPONSES},
)
async def put_group(
    group_id: UUID, body: GroupIn, principal: CanManage, conn: DbConnection, clock: ClockDep
) -> GroupOut:
    try:
        group = await update_group(
            _actor(principal), group_id, body.data, groups=SqlGroupRepository(conn),
            audit=SqlAuditLog(conn), clock=clock,
        )  # fmt: skip
    except GroupNotFoundError as exc:
        raise _NOT_FOUND from exc
    except InvalidGroupError as exc:
        raise _invalid(exc) from exc
    except DuplicateGroupNameError as exc:
        raise _DUPLICATE from exc
    return _out(group)


@router.delete(
    "/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a group that no policy notifies",
    responses={
        404: {"description": "Not found"},
        409: {"description": "A policy notifies it; the detail names which"},
    },
)
async def remove_group(
    group_id: UUID, principal: CanManage, conn: DbConnection, clock: ClockDep
) -> Response:
    try:
        await delete_group(
            _actor(principal), group_id, groups=SqlGroupRepository(conn),
            audit=SqlAuditLog(conn), clock=clock,
        )  # fmt: skip
    except GroupNotFoundError as exc:
        raise _NOT_FOUND from exc
    except GroupInUseError as exc:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            ErrorCode.GROUP_IN_USE,
            group=exc.group.name,
            policies=Names(policy.name for policy in exc.group.policies),
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _actor(principal: Principal) -> Actor:
    return Actor(principal.organization_id, principal.user_id)


def _invalid(exc: InvalidGroupError) -> ApiError:
    return invalid_field(exc)


def _ref(ref: Ref) -> RefOut:
    return RefOut(id=ref.id, name=ref.name)


def _out(group: ContactGroup) -> GroupOut:
    return GroupOut(
        id=group.id,
        name=group.name,
        zone=_ref(group.zone) if group.zone is not None else None,
        members=[_ref(m) for m in group.members],
        policies=[_ref(p) for p in group.policies],
    )
