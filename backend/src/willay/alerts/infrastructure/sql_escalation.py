"""EscalationRepository: levels are read from the current policy when escalating (SPEC)."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from willay.alerts.domain.escalation import LevelState

# "Nobody alerted": every alert of the current level is `skipped` (missing channel).
_NOBODY_ALERTED = """
    NOT EXISTS (SELECT 1 FROM core.alerts a
                WHERE a.incident_id = i.id AND a.level_order = i.current_level
                  AND a.status <> 'skipped')
"""

# Due when the level expired, alerted nobody, or no longer exists in the policy.
_DUE = text(f"""
    SELECT i.id
    FROM core.incidents i
    JOIN core.rules r ON r.id = i.rule_id
    LEFT JOIN core.escalation_levels cur ON cur.policy_id = r.escalation_policy_id
                                        AND cur.level_order = i.current_level
    WHERE i.status = 'open' AND i.escalation_exhausted_at IS NULL
      AND (cur.id IS NULL
           OR i.level_started_at + cur.wait_s * interval '1 second' <= :now
           OR {_NOBODY_ALERTED})
    ORDER BY i.level_started_at
    LIMIT :limit
""")

# SKIP LOCKED: if another worker is escalating it, or someone is acknowledging it, it is
# left for the next cycle. Only the incident is locked; levels are read as they are.
_LOCK = text(f"""
    SELECT i.current_level, i.level_started_at, cur.wait_s,
           (SELECT min(n.level_order) FROM core.escalation_levels n
            WHERE n.policy_id = r.escalation_policy_id
              AND n.level_order > i.current_level) AS next_level,
           {_NOBODY_ALERTED} AS nobody_alerted
    FROM core.incidents i
    JOIN core.rules r ON r.id = i.rule_id
    LEFT JOIN core.escalation_levels cur ON cur.policy_id = r.escalation_policy_id
                                        AND cur.level_order = i.current_level
    WHERE i.id = :id AND i.status = 'open' AND i.escalation_exhausted_at IS NULL
    FOR UPDATE OF i SKIP LOCKED
""")

_MOVE = text("""
    UPDATE core.incidents SET current_level = :level, level_started_at = :now WHERE id = :id
""")

_EXHAUST = text("UPDATE core.incidents SET escalation_exhausted_at = :now WHERE id = :id")

_EVENT = text("""
    INSERT INTO core.incident_events (incident_id, organization_id, occurred_at, event_type,
                                      actor_type, payload)
    SELECT i.id, i.organization_id, :now, :event_type, 'system', CAST(:payload AS jsonb)
    FROM core.incidents i WHERE i.id = :id
""")


class SqlEscalationRepository:
    async def due(self, tx: AsyncConnection, now: datetime, limit: int) -> list[UUID]:
        rows = await tx.execute(_DUE, {"now": now, "limit": limit})
        return [r.id for r in rows]

    async def lock(self, tx: AsyncConnection, incident_id: UUID) -> LevelState | None:
        row = (await tx.execute(_LOCK, {"id": incident_id})).first()
        if row is None:
            return None
        return LevelState(
            current_level=row.current_level,
            level_started_at=row.level_started_at,
            wait_s=row.wait_s,
            next_level=row.next_level,
            nobody_alerted=row.nobody_alerted,
        )

    async def move_to_level(
        self, tx: AsyncConnection, incident_id: UUID, level: int, now: datetime
    ) -> None:
        await tx.execute(_MOVE, {"id": incident_id, "level": level, "now": now})

    async def exhaust(self, tx: AsyncConnection, incident_id: UUID, now: datetime) -> None:
        await tx.execute(_EXHAUST, {"id": incident_id, "now": now})

    async def record(
        self,
        tx: AsyncConnection,
        incident_id: UUID,
        event_type: str,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        await tx.execute(
            _EVENT,
            {
                "id": incident_id,
                "now": now,
                "event_type": event_type,
                "payload": json.dumps(payload),
            },
        )
