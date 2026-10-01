"""Audit log (core.audit_log, append-only through DB privileges).

Use cases record the entry on the SAME connection that makes the change, so both commit or
neither does. `vigia_app` can only insert here (ADR-0005), never rewrite.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class AuditEntry:
    organization_id: UUID
    actor_id: UUID | None  # user (Keycloak sub); None when done by the system
    entity_type: str
    entity_id: UUID
    action: str  # create, update, deactivate, ...
    before: Mapping[str, Any] | None
    after: Mapping[str, Any] | None
    at: datetime


class AuditLog(Protocol):
    async def record(self, entry: AuditEntry) -> None: ...


class SqlAuditLog:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def record(self, entry: AuditEntry) -> None:
        await self._conn.execute(
            text("""
                INSERT INTO core.audit_log (organization_id, actor_id, entity_type, entity_id,
                                            action, before, after, at)
                VALUES (:organization_id, :actor_id, :entity_type, :entity_id, :action,
                        CAST(:before AS jsonb), CAST(:after AS jsonb), :at)
            """),
            {
                "organization_id": entry.organization_id,
                "actor_id": entry.actor_id,
                "entity_type": entry.entity_type,
                "entity_id": entry.entity_id,
                "action": entry.action,
                "before": _json(entry.before),
                "after": _json(entry.after),
                "at": entry.at,
            },
        )


def _json(snapshot: Mapping[str, Any] | None) -> str | None:
    # default=str: uuids and datetimes become readable text in the jsonb.
    return None if snapshot is None else json.dumps(snapshot, default=str, ensure_ascii=False)
