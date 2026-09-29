"""EvaluationQueue sobre ingest.evaluation_queue (Postgres, FOR UPDATE SKIP LOCKED)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from vigia.rules.application.queue import (
    MAX_ATTEMPTS,
    VISIBILITY_TIMEOUT,
    LostClaimError,
    QueuedReading,
)
from vigia.shared.clock import Clock

# Filas que ya agotaron sus intentos sin completar ni fallar: el worker murió durante el
# último. Se marcan como fallidas en lugar de evaluarse una sexta vez.
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

# SKIP LOCKED: si otro worker ya bloqueó una fila, se salta en lugar de esperarla. Así
# varios evaluadores se reparten la cola sin tomar nunca la misma fila a la vez.
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
    RETURNING q.id, q.station_id, q.organization_id, q.measured_at, q.attempts
""")


class PostgresEvaluationQueue:
    def __init__(self, engine: AsyncEngine, clock: Clock) -> None:
        self._engine = engine
        self._clock = clock

    async def claim(self, limit: int) -> list[QueuedReading]:
        now = self._clock.now()
        async with self._engine.begin() as conn:  # transacción corta propia
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
                QueuedReading(r.id, r.station_id, r.organization_id, r.measured_at, r.attempts)
                for r in rows
            ]
        return sorted(items, key=lambda item: (item.measured_at, item.queue_id))

    async def complete(self, tx: AsyncConnection, item: QueuedReading) -> None:
        # Guardia de propiedad: si otro worker retomó la fila tras el timeout, attempts ya
        # no coincide y no se borra nada. La evaluación se revierte en lugar de duplicarse.
        deleted = await tx.scalar(
            text("""
                DELETE FROM ingest.evaluation_queue
                WHERE id = :id AND attempts = :attempt AND failed_at IS NULL
                RETURNING id
            """),
            {"id": item.queue_id, "attempt": item.attempt},
        )
        if deleted is None:
            raise LostClaimError(f"la fila {item.queue_id} ya no pertenece a este intento")
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
