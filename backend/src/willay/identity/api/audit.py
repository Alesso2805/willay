"""Audit log API (VIG-38): admin only (SPEC: "See the audit log")."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from willay.identity.api.dependencies import require
from willay.identity.application.audit_trail import AuditFilters, AuditRecord, read_page
from willay.identity.domain.audit_trail import (
    DEFAULT_PAGE,
    MAX_PAGE,
    EntityType,
    InvalidCursorError,
    decode_cursor,
)
from willay.identity.domain.permissions import Permission
from willay.identity.domain.principal import Principal
from willay.identity.infrastructure.sql_audit_trail import SqlAuditTrail
from willay.shared.web import DbConnection

router = APIRouter(prefix="/v1/audit", tags=["identity"])

CanView = Annotated[Principal, Depends(require(Permission.VIEW_AUDIT_LOG))]


class AuthorOut(BaseModel):
    id: UUID
    name: str


class AuditEntryOut(BaseModel):
    id: int
    at: datetime
    actor: AuthorOut | None = Field(
        description="None when nobody from the organization did it (the contact from Telegram)"
    )
    entity_type: str
    entity_id: UUID
    entity_name: str | None = Field(
        description="Its current name, for entries whose snapshot has none; None once deleted"
    )
    action: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None


class AuditPageOut(BaseModel):
    items: list[AuditEntryOut]
    next_cursor: str | None = Field(
        description="Pass it as `cursor` for the next page; None at the end"
    )


@router.get(
    "",
    summary="The organization's audit log, most recent first, cursor-paginated",
    responses={422: {"description": "An unreadable cursor, or `since` not before `until`"}},
)
async def list_audit(
    principal: CanView,
    conn: DbConnection,
    entity_type: EntityType | None = None,
    entity_id: UUID | None = None,
    actor_id: UUID | None = None,
    since: Annotated[datetime | None, Query(description="Inclusive")] = None,
    until: Annotated[datetime | None, Query(description="Exclusive")] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = DEFAULT_PAGE,
) -> AuditPageOut:
    if since is not None and until is not None and since >= until:
        raise _invalid("since", "La fecha inicial debe ser anterior a la final.")
    try:
        after = decode_cursor(cursor) if cursor is not None else None
    except InvalidCursorError as exc:
        raise _invalid("cursor", "El cursor no es válido: vuelve a la primera página.") from exc
    page = await read_page(
        principal.organization_id,
        AuditFilters(entity_type, entity_id, actor_id, since, until),
        after,
        limit,
        trail=SqlAuditTrail(conn),
    )
    return AuditPageOut(items=[_out(r) for r in page.records], next_cursor=page.next_cursor)


@router.get("/authors", summary="Users who appear in the audit log, for the author filter")
async def list_authors(principal: CanView, conn: DbConnection) -> list[AuthorOut]:
    authors = await SqlAuditTrail(conn).authors(principal.organization_id)
    return [AuthorOut(id=a.id, name=a.name) for a in authors]


def _invalid(field: str, message: str) -> HTTPException:
    """The same shape as FastAPI's own validation errors."""
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[{"loc": ["query", field], "msg": message, "type": "value_error"}],
    )


def _out(record: AuditRecord) -> AuditEntryOut:
    actor = (
        AuthorOut(id=record.actor_id, name=record.actor_name or "Usuario desconocido")
        if record.actor_id is not None
        else None
    )
    return AuditEntryOut(
        id=record.id,
        at=record.at,
        actor=actor,
        entity_type=record.entity_type,
        entity_id=record.entity_id,
        entity_name=record.entity_name,
        action=record.action,
        before=dict(record.before) if record.before is not None else None,
        after=dict(record.after) if record.after is not None else None,
    )
