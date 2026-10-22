"""Reading → first alert latencies from the database."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# One value per incident opened by a reading in the period: its first alert actually sent.
_LATENCIES = text("""
    SELECT EXTRACT(EPOCH FROM min(a.sent_at) - i.trigger_received_at) AS seconds
    FROM core.incidents i
    JOIN core.alerts a ON a.incident_id = i.id AND a.sent_at IS NOT NULL
    WHERE i.trigger_received_at IS NOT NULL
      AND i.opened_at >= :since AND i.opened_at < :until
      AND (CAST(:organization_id AS uuid) IS NULL OR i.organization_id = :organization_id)
    GROUP BY i.id, i.trigger_received_at
""")


async def received_to_alert_seconds(
    conn: AsyncConnection,
    since: datetime,
    until: datetime,
    organization_id: UUID | None = None,
) -> list[float]:
    """Every organization's, or only `organization_id`'s (the load test measures its own)."""
    rows = await conn.execute(
        _LATENCIES, {"since": since, "until": until, "organization_id": organization_id}
    )
    return [float(r.seconds) for r in rows]
