"""IncidentRepository over core.incidents and core.incident_events (willay_app role)."""

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncConnection

from willay.incidents.application.lifecycle import EventActor, Incident, IncidentEvent
from willay.incidents.domain.lifecycle import IncidentStatus, Resolution
from willay.incidents.domain.severity import Severity

# Zone and rule always exist (they are deactivated, never deleted); the station may be
# missing if a future rule type has none.
_SELECT = """
    SELECT i.id, i.zone_id, z.name AS zone_name, i.station_id, s.code AS station_code,
           i.rule_id, r.type AS rule_type, i.severity, i.status, i.current_level,
           i.trigger_value, i.opened_at, i.escalation_exhausted_at, i.acknowledged_at,
           i.acknowledged_by_user_id, i.acknowledged_by_contact_id, i.resolved_at,
           i.resolution
    FROM core.incidents i
    JOIN core.risk_zones z ON z.id = i.zone_id
    JOIN core.rules r ON r.id = i.rule_id
    LEFT JOIN core.stations s ON s.id = i.station_id
"""

_LIST = text(
    _SELECT
    + """
    WHERE i.organization_id = :organization_id
      AND (cardinality(CAST(:statuses AS text[])) = 0
           OR i.status = ANY(CAST(:statuses AS text[])))
      AND (cardinality(CAST(:severities AS text[])) = 0
           OR i.severity = ANY(CAST(:severities AS text[])))
    ORDER BY i.opened_at DESC, i.id DESC
    LIMIT :limit
"""
)

_GET = text(_SELECT + " WHERE i.organization_id = :organization_id AND i.id = :id")

# Names are joined within the event's own organization; alert events carry the recipient in
# payload.contact_id (compared as text, so an odd payload cannot break the query with a cast).
_TIMELINE = text("""
    SELECT e.id, e.occurred_at, e.event_type, e.actor_type, e.actor_id, e.payload,
           COALESCE(u.full_name, ac.full_name) AS actor_name,
           rc.full_name AS contact_name
    FROM core.incident_events e
    LEFT JOIN core.users u
           ON e.actor_type = 'user' AND u.id = e.actor_id
          AND u.organization_id = e.organization_id
    LEFT JOIN core.contacts ac
           ON e.actor_type = 'contact' AND ac.id = e.actor_id
          AND ac.organization_id = e.organization_id
    LEFT JOIN core.contacts rc
           ON CAST(rc.id AS text) = e.payload->>'contact_id'
          AND rc.organization_id = e.organization_id
    WHERE e.incident_id = :id
    ORDER BY e.occurred_at, e.id
""")

_LOCK = text("""
    SELECT status FROM core.incidents
    WHERE organization_id = :organization_id AND id = :id
    FOR UPDATE
""")

# Only one of the acknowledged_by_* columns gets a value (CHECK in migration 0002).
_ACKNOWLEDGE = text("""
    UPDATE core.incidents
    SET status = 'acknowledged', acknowledged_at = :now,
        acknowledged_by_user_id = :user_id, acknowledged_by_contact_id = :contact_id
    WHERE id = :id
""")

_RESOLVE = text("""
    UPDATE core.incidents
    SET status = 'resolved', resolved_at = :now, resolution = :resolution
    WHERE id = :id
""")

_EVENT = text("""
    INSERT INTO core.incident_events (incident_id, organization_id, occurred_at, event_type,
                                      actor_type, actor_id, payload)
    VALUES (:incident_id, :organization_id, :now, :event_type, :actor_type, :actor_id,
            CAST(:payload AS jsonb))
    RETURNING id
""")


class SqlIncidentRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def recent(
        self,
        organization_id: UUID,
        statuses: Sequence[IncidentStatus],
        severities: Sequence[Severity],
        limit: int,
    ) -> list[Incident]:
        """Newest first; an empty filter does not filter. Filtering here, not in the client,
        keeps `limit` meaningful: it applies to the incidents that match."""
        rows = await self._conn.execute(
            _LIST,
            {
                "organization_id": organization_id,
                "statuses": [s.value for s in statuses],
                "severities": [s.value for s in severities],
                "limit": limit,
            },
        )
        return [_incident(r) for r in rows]

    async def get(self, organization_id: UUID, incident_id: UUID) -> Incident | None:
        rows = await self._conn.execute(
            _GET, {"organization_id": organization_id, "id": incident_id}
        )
        row = rows.first()
        return _incident(row) if row is not None else None

    async def timeline(self, incident_id: UUID) -> list[IncidentEvent]:
        rows = await self._conn.execute(_TIMELINE, {"id": incident_id})
        return [
            IncidentEvent(
                r.id,
                r.occurred_at,
                r.event_type,
                r.actor_type,
                r.actor_id,
                r.payload,
                actor_name=r.actor_name,
                contact_name=r.contact_name,
            )
            for r in rows
        ]

    async def lock_status(self, organization_id: UUID, incident_id: UUID) -> IncidentStatus | None:
        status = await self._conn.scalar(
            _LOCK, {"organization_id": organization_id, "id": incident_id}
        )
        return IncidentStatus(status) if status is not None else None

    async def acknowledge(self, incident_id: UUID, actor: EventActor, now: datetime) -> None:
        by_user = actor.actor_type == "user"
        await self._conn.execute(
            _ACKNOWLEDGE,
            {
                "id": incident_id,
                "now": now,
                "user_id": actor.actor_id if by_user else None,
                "contact_id": None if by_user else actor.actor_id,
            },
        )

    async def resolve(self, incident_id: UUID, resolution: Resolution, now: datetime) -> None:
        await self._conn.execute(
            _RESOLVE, {"id": incident_id, "resolution": resolution.value, "now": now}
        )

    async def add_event(
        self,
        incident_id: UUID,
        actor: EventActor,
        event_type: str,
        payload: Mapping[str, Any],
        now: datetime,
    ) -> int:
        event_id: int = await self._conn.scalar(
            _EVENT,
            {
                "incident_id": incident_id,
                "organization_id": actor.organization_id,
                "now": now,
                "event_type": event_type,
                "actor_type": actor.actor_type,
                "actor_id": actor.actor_id,
                "payload": json.dumps(dict(payload)),
            },
        )
        return event_id


def _incident(r: Row[Any]) -> Incident:
    return Incident(
        id=r.id,
        zone_id=r.zone_id,
        zone_name=r.zone_name,
        station_id=r.station_id,
        station_code=r.station_code,
        rule_id=r.rule_id,
        rule_type=r.rule_type,
        severity=r.severity,
        status=IncidentStatus(r.status),
        current_level=r.current_level,
        trigger_value=r.trigger_value,
        opened_at=r.opened_at,
        escalation_exhausted_at=r.escalation_exhausted_at,
        acknowledged_at=r.acknowledged_at,
        acknowledged_by_user_id=r.acknowledged_by_user_id,
        acknowledged_by_contact_id=r.acknowledged_by_contact_id,
        resolved_at=r.resolved_at,
        resolution=Resolution(r.resolution) if r.resolution is not None else None,
    )
