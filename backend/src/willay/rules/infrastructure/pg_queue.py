"""EvaluationQueue over ingest.evaluation_queue (Postgres, FOR UPDATE SKIP LOCKED)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from willay.rules.application.queue import (
    MAX_ATTEMPTS,
    VISIBILITY_TIMEOUT,
    LostClaimError,
    QueuedReading,
)
from willay.shared.clock import Clock

# Rows that used up their attempts without completing or failing: the worker died during
# the last one. They are marked failed instead of being evaluated a sixth time.
_ABANDON = text("""
    UPDATE ingest.evaluation_queue
    SET failed_at = :now,
        last_error = coalesce(last_error || ' | ', '')
                     || 'sin completar tras ' || attempts || ' intentos'
    WHERE id IN (
        SELECT id FROM ingest.evaluation_queue
        WHERE failed_at IS NULL AND available_at <= :now AND attempts >= :max_attempts
        FOR UPDATE SKIP LOCKED
    )
""")

# SKIP LOCKED: a row already locked by another worker is skipped instead of awaited, so
# several evaluators share the queue without ever claiming the same row at once.
_CLAIM = text("""
    WITH picked AS (
        SELECT id FROM ingest.evaluation_queue
        WHERE failed_at IS NULL AND available_at <= :now AND attempts < :max_attempts
        ORDER BY available_at, id
        LIMIT :limit
        FOR UPDATE SKIP LOCKED
    )
    UPDATE ingest.evaluation_queue AS q
    SET attempts = q.attempts + 1, available_at = :visible_again_at
    FROM picked
    WHERE q.id = picked.id
    RETURNING q.id, q.station_id, q.organization_id, q.measured_at, q.attempts,
              q.correlation_id, q.enqueued_at
""")


class PostgresEvaluationQueue:
    def __init__(self, engine: AsyncEngine, clock: Clock) -> None:
        self._engine = engine
        self._clock = clock

    async def claim(self, limit: int) -> list[QueuedReading]:
        now = self._clock.now()
        async with self._engine.begin() as conn:  # its own short transaction
            await conn.execute(_ABANDON, {"now": now, "max_attempts": MAX_ATTEMPTS})
            rows = await conn.execute(
                _CLAIM,
                {
                    "now": now,
                    "max_attempts": MAX_ATTEMPTS,
                    "limit": limit,
                    "visible_again_at": now + VISIBILITY_TIMEOUT,
                },
            )
            items = [
                QueuedReading(
                    r.id,
                    r.station_id,
                    r.organization_id,
                    r.measured_at,
                    r.attempts,
                    r.correlation_id,
                    r.enqueued_at,
                )
                for r in rows
            ]
        return sorted(items, key=lambda item: (item.measured_at, item.queue_id))

    async def complete(self, tx: AsyncConnection, item: QueuedReading) -> None:
        # Ownership guard: if another worker reclaimed the row after the timeout, attempts no
        # longer matches and nothing is deleted. The evaluation rolls back instead of doubling.
        deleted = await tx.scalar(
            text("""
                DELETE FROM ingest.evaluation_queue
                WHERE id = :id AND attempts = :attempt AND failed_at IS NULL
                RETURNING id
            """),
            {"id": item.queue_id, "attempt": item.attempt},
        )
        if deleted is None:
            raise LostClaimError(f"row {item.queue_id} no longer belongs to this attempt")
        await tx.execute(
            text("""
                UPDATE ingest.readings SET evaluated_at = :now
                WHERE station_id = :station_id AND measured_at = :measured_at
            """),
            {
                "now": self._clock.now(),
                "station_id": item.station_id,
                "measured_at": item.measured_at,
            },
        )

    async def fail(self, item: QueuedReading, error: str) -> bool:
        final = item.attempt >= MAX_ATTEMPTS
        async with self._engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE ingest.evaluation_queue
                    SET last_error = :error,
                        failed_at = CASE WHEN :final THEN CAST(:now AS timestamptz) END
                    WHERE id = :id AND attempts = :attempt AND failed_at IS NULL
                """),
                {
                    "id": item.queue_id,
                    "attempt": item.attempt,
                    "error": error[:2000],
                    "final": final,
                    "now": self._clock.now(),
                },
            )
        return final
