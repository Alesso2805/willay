"""FailedReadingRepository over ingest.evaluation_queue."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncConnection

from willay.rules.application.failed_readings import FailedReading
from willay.shared import notifications

# The reading's value comes from the hypertable when it is still there (no FK: ADR-0003).
_COLUMNS = """
    q.id, q.station_id, s.code AS station_code, s.name AS station_name, q.measured_at,
    r.value, s.unit, q.attempts, q.failed_at, q.last_error
"""
_JOINS = """
    JOIN core.stations s ON s.id = q.station_id
    LEFT JOIN ingest.readings r
        ON r.station_id = q.station_id AND r.measured_at = q.measured_at
"""

_ALL = text(f"""
    SELECT {_COLUMNS}
    FROM ingest.evaluation_queue q {_JOINS}
    WHERE q.organization_id = :organization_id AND q.failed_at IS NOT NULL
    ORDER BY q.failed_at DESC, q.id DESC
    LIMIT :limit
""")

_COUNT = text("""
    SELECT count(*) FROM ingest.evaluation_queue
    WHERE organization_id = :organization_id AND failed_at IS NOT NULL
""")

# FOR UPDATE: if two operators reprocess the same rows at once, the second waits, then sees
# them no longer failed and skips them, so each row is requeued and audited once.
_REQUEUE = text(f"""
    WITH picked AS (
        SELECT q.id FROM ingest.evaluation_queue q
        WHERE q.organization_id = :organization_id AND q.failed_at IS NOT NULL
          AND q.id = ANY(CAST(:ids AS bigint[]))
        FOR UPDATE
    ),
    previous AS (
        SELECT {_COLUMNS}
        FROM ingest.evaluation_queue q {_JOINS}
        WHERE q.id IN (SELECT id FROM picked)
    ),
    requeued AS (
        UPDATE ingest.evaluation_queue q
        SET failed_at = NULL, attempts = 0, available_at = :now
        WHERE q.id IN (SELECT id FROM picked)
    )
    SELECT * FROM previous ORDER BY measured_at, id
""")

_WAKE_EVALUATOR = text("SELECT pg_notify(:channel, '')")


class SqlFailedReadingRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def all_of(self, organization_id: UUID, *, limit: int) -> list[FailedReading]:
        rows = await self._conn.execute(_ALL, {"organization_id": organization_id, "limit": limit})
        return [_failed(r) for r in rows]

    async def count(self, organization_id: UUID) -> int:
        return int(await self._conn.scalar(_COUNT, {"organization_id": organization_id}) or 0)

    async def requeue(
        self, organization_id: UUID, ids: frozenset[int], now: datetime
    ) -> list[FailedReading]:
        if not ids:
            return []
        rows = await self._conn.execute(
            _REQUEUE, {"organization_id": organization_id, "ids": sorted(ids), "now": now}
        )
        requeued = [_failed(r) for r in rows]
        if requeued:
            # Delivered on commit, like ingestion's: the evaluator does not wait for its poll.
            await self._conn.execute(_WAKE_EVALUATOR, {"channel": notifications.EVALUATION_QUEUE})
        return requeued


def _failed(r: Row[Any]) -> FailedReading:
    return FailedReading(
        id=r.id,
        station_id=r.station_id,
        station_code=r.station_code,
        station_name=r.station_name,
        measured_at=r.measured_at,
        value=r.value,
        unit=r.unit,
        attempts=r.attempts,
        failed_at=r.failed_at,
        last_error=r.last_error,
    )
