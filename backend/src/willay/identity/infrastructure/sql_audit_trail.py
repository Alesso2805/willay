"""AuditTrail over core.audit_log. Read only: the table is append-only anyway."""

from typing import Any
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncConnection

from willay.identity.application.audit_trail import AuditFilters, AuditRecord, Author
from willay.identity.domain.audit_trail import Cursor

# The entity's current name, for entries whose snapshot does not carry one (e.g. a Telegram
# link only records its expiry). None once the entity is gone; rules are named by their
# snapshot (zone and station), so they are not looked up.
_CURRENT_NAME = """
    CASE a.entity_type
        WHEN 'risk_zone' THEN (SELECT name FROM core.risk_zones
                               WHERE id = a.entity_id AND organization_id = a.organization_id)
        WHEN 'station' THEN (SELECT code FROM core.stations
                             WHERE id = a.entity_id AND organization_id = a.organization_id)
        WHEN 'contact' THEN (SELECT full_name FROM core.contacts
                             WHERE id = a.entity_id AND organization_id = a.organization_id)
        WHEN 'contact_group' THEN (SELECT name FROM core.contact_groups
                                   WHERE id = a.entity_id AND organization_id = a.organization_id)
        WHEN 'escalation_policy' THEN (
            SELECT name FROM core.escalation_policies
            WHERE id = a.entity_id AND organization_id = a.organization_id)
    END
"""

# Each filter applies only when given. The (at, id) row comparison resumes after the cursor
# and walks the (organization_id, at) index backwards.
_PAGE = text(f"""
    SELECT a.id, a.at, a.actor_id, u.full_name AS actor_name, a.entity_type, a.entity_id,
           {_CURRENT_NAME} AS entity_name, a.action, a.before, a.after
    FROM core.audit_log a
    LEFT JOIN core.users u ON u.id = a.actor_id AND u.organization_id = a.organization_id
    WHERE a.organization_id = :organization_id
      AND (CAST(:entity_type AS text) IS NULL OR a.entity_type = :entity_type)
      AND (CAST(:entity_id AS uuid) IS NULL OR a.entity_id = :entity_id)
      AND (CAST(:actor_id AS uuid) IS NULL OR a.actor_id = :actor_id)
      AND (CAST(:since AS timestamptz) IS NULL OR a.at >= :since)
      AND (CAST(:until AS timestamptz) IS NULL OR a.at < :until)
      AND (CAST(:cursor_at AS timestamptz) IS NULL
           OR (a.at, a.id) < (CAST(:cursor_at AS timestamptz), CAST(:cursor_id AS bigint)))
    ORDER BY a.at DESC, a.id DESC
    LIMIT :limit
""")

_AUTHORS = text("""
    SELECT DISTINCT u.id, u.full_name
    FROM core.audit_log a
    JOIN core.users u ON u.id = a.actor_id AND u.organization_id = a.organization_id
    WHERE a.organization_id = :organization_id
    ORDER BY u.full_name, u.id
""")


class SqlAuditTrail:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def page(
        self, organization_id: UUID, filters: AuditFilters, after: Cursor | None, limit: int
    ) -> list[AuditRecord]:
        rows = await self._conn.execute(
            _PAGE,
            {
                "organization_id": organization_id,
                "entity_type": filters.entity_type.value if filters.entity_type else None,
                "entity_id": filters.entity_id,
                "actor_id": filters.actor_id,
                "since": filters.since,
                "until": filters.until,
                "cursor_at": after.at if after else None,
                "cursor_id": after.id if after else None,
                "limit": limit,
            },
        )
        return [_record(r) for r in rows]

    async def authors(self, organization_id: UUID) -> list[Author]:
        rows = await self._conn.execute(_AUTHORS, {"organization_id": organization_id})
        return [Author(r.id, r.full_name) for r in rows]


def _record(r: Row[Any]) -> AuditRecord:
    return AuditRecord(
        id=r.id,
        at=r.at,
        actor_id=r.actor_id,
        actor_name=r.actor_name,
        entity_type=r.entity_type,
        entity_id=r.entity_id,
        entity_name=r.entity_name,
        action=r.action,
        before=r.before,
        after=r.after,
    )
