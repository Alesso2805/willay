"""Registro de auditoría (core.audit_log, append-only por permisos de BD).

SPEC pide auditar cambios en zonas, estaciones, reglas, políticas y contactos. Cada caso
de uso registra la entrada con la MISMA conexión que hace el cambio: o quedan los dos o
ninguno. `vigia_app` solo puede insertar aquí (ADR-0005), nunca reescribir.
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
    actor_id: UUID | None  # usuario (sub de Keycloak); None si lo hizo el sistema
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
    # default=str: uuids y fechas quedan como texto legible en el jsonb.
    return None if snapshot is None else json.dumps(snapshot, default=str, ensure_ascii=False)
