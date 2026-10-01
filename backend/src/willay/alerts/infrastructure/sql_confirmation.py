"""ConfirmationRepository over core.alerts (willay_app role, in the request's transaction)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from willay.alerts.application.confirmation import AlertToConfirm
from willay.alerts.infrastructure.alert_messages import (
    MESSAGE_COLUMNS,
    MESSAGE_JOINS,
    message_from_row,
)
from willay.incidents.domain.lifecycle import IncidentStatus

# Looked up by hash: the database never stores or receives the plain token. The incident
# may have been acknowledged by a user (with an account) or by a contact.
# The f-string only joins fixed fragments from alert_messages; data goes as parameters.
_FIND = f"""
    SELECT a.id AS alert_id, a.incident_id, i.organization_id, a.contact_id, a.destination,
           a.ack_token_expires_at, a.acknowledged_at AS used_at,
           i.status AS incident_status, i.acknowledged_at AS incident_acknowledged_at,
           COALESCE(u.full_name, ack.full_name) AS acknowledged_by,
           {MESSAGE_COLUMNS}
    FROM core.alerts a
    {MESSAGE_JOINS}
    LEFT JOIN core.users u ON u.id = i.acknowledged_by_user_id
    LEFT JOIN core.contacts ack ON ack.id = i.acknowledged_by_contact_id
    WHERE a.ack_token_hash = :token_hash
"""

_FIND_PLAIN = text(_FIND)
_FIND_LOCKED = text(_FIND + " FOR UPDATE OF a")

# An acknowledged alert is no longer retried: next_attempt_at becomes NULL.
_MARK_ACKNOWLEDGED = text("""
    UPDATE core.alerts
    SET status = 'acknowledged', acknowledged_at = :now, next_attempt_at = NULL
    WHERE id = :id
""")


class SqlConfirmationRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def find(self, token_hash: str, *, lock: bool) -> AlertToConfirm | None:
        query = _FIND_LOCKED if lock else _FIND_PLAIN
        row = (await self._conn.execute(query, {"token_hash": token_hash})).first()
        if row is None:
            return None
        return AlertToConfirm(
            alert_id=row.alert_id,
            incident_id=row.incident_id,
            organization_id=row.organization_id,
            contact_id=row.contact_id,
            destination=row.destination,
            token_expires_at=row.ack_token_expires_at,
            used_at=row.used_at,
            incident_status=IncidentStatus(row.incident_status),
            incident_acknowledged_at=row.incident_acknowledged_at,
            acknowledged_by=row.acknowledged_by,
            message=message_from_row(row),
        )

    async def mark_acknowledged(self, alert_id: UUID, now: datetime) -> None:
        await self._conn.execute(_MARK_ACKNOWLEDGED, {"id": alert_id, "now": now})
