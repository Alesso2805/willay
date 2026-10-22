"""What the load test reads back from the database once its readings have settled."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# SPEC's reliability check: zero `ok` readings without evaluated_at 120 s after reception.
_UNEVALUATED = text("""
    SELECT count(*) FROM ingest.readings
    WHERE organization_id = :organization_id AND quality = 'ok'
      AND received_at >= :since AND evaluated_at IS NULL
""")

_STORED = text("""
    SELECT count(*) FROM ingest.readings
    WHERE organization_id = :organization_id AND received_at >= :since
""")


async def unevaluated(conn: AsyncConnection, organization_id: UUID, since: datetime) -> int:
    params = {"organization_id": organization_id, "since": since}
    return int(await conn.scalar(_UNEVALUATED, params) or 0)


async def stored(conn: AsyncConnection, organization_id: UUID, since: datetime) -> int:
    params = {"organization_id": organization_id, "since": since}
    return int(await conn.scalar(_STORED, params) or 0)
