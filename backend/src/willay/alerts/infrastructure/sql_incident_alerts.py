"""An incident's alerts, by recipient, for its detail page."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from willay.alerts.domain.alerts import AlertStatus, Channel

_EXISTS = text("""
    SELECT 1 FROM core.incidents WHERE organization_id = :organization_id AND id = :incident_id
""")

# A skipped alert keeps its reason only in its `alert_skipped` event: the event is matched by
# recipient, channel and level (the planner's events have no alert id), compared as text.
_ALERTS = text("""
    SELECT a.id, a.level_order, a.contact_id, c.full_name AS contact_name, a.channel, a.status,
           a.attempts, a.sent_at, a.acknowledged_at, a.destination,
           skipped.reason_code AS skipped_reason_code, skipped.reason AS skipped_reason
    FROM core.incidents i
    JOIN core.alerts a ON a.incident_id = i.id
    JOIN core.contacts c ON c.id = a.contact_id AND c.organization_id = i.organization_id
    LEFT JOIN LATERAL (
        SELECT e.payload->>'reason_code' AS reason_code, e.payload->>'reason' AS reason
        FROM core.incident_events e
        WHERE e.incident_id = a.incident_id AND e.event_type = 'alert_skipped'
          AND e.payload->>'contact_id' = CAST(a.contact_id AS text)
          AND e.payload->>'channel' = a.channel
          AND e.payload->>'level_order' = CAST(a.level_order AS text)
        ORDER BY e.id DESC
        LIMIT 1
    ) skipped ON a.status = 'skipped'
    WHERE i.organization_id = :organization_id AND i.id = :incident_id
    ORDER BY a.level_order, c.full_name, a.channel
""")


@dataclass(frozen=True)
class IncidentAlert:
    id: UUID
    level_order: int
    contact_id: UUID
    contact_name: str
    channel: Channel
    status: AlertStatus
    attempts: int
    sent_at: datetime | None
    acknowledged_at: datetime | None
    destination: str | None  # personal data: the API decides who sees it
    skipped_reason_code: str | None
    skipped_reason: str | None  # Spanish text, only in events from before VIG-40


class SqlIncidentAlerts:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def for_incident(
        self, organization_id: UUID, incident_id: UUID
    ) -> list[IncidentAlert] | None:
        """By level, recipient and channel; None if the incident is not this organization's."""
        params = {"organization_id": organization_id, "incident_id": incident_id}
        if await self._conn.scalar(_EXISTS, params) is None:
            return None
        rows = await self._conn.execute(_ALERTS, params)
        return [
            IncidentAlert(
                r.id,
                r.level_order,
                r.contact_id,
                r.contact_name,
                Channel(r.channel),
                AlertStatus(r.status),
                r.attempts,
                r.sent_at,
                r.acknowledged_at,
                r.destination,
                r.skipped_reason_code,
                r.skipped_reason,
            )
            for r in rows
        ]
