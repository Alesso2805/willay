"""Repositorios SQL de ingesta (rol vigia_app)."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from vigia.ingestion.application.authenticate_station import StationCredential
from vigia.ingestion.application.ingest_batch import StoreCounts
from vigia.ingestion.domain.readings import ClassifiedReading
from vigia.shared import notifications


class SqlStationCredentials:
    """Lectura en una conexión propia y breve: se devuelve al pool antes de verificar el
    hash Argon2id (decenas de ms), en lugar de retenerla durante el cálculo."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def find(self, station_id: UUID) -> StationCredential | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text("""
                        SELECT id, organization_id, api_key_hash, status = 'active' AS is_active
                        FROM core.stations WHERE id = :id
                    """),
                    {"id": station_id},
                )
            ).one_or_none()
        if row is None:
            return None
        return StationCredential(row.id, row.organization_id, row.api_key_hash, row.is_active)


class SqlBatchCounter:
    """Contador de lotes por estación y minuto en ingest.rate_limit_windows.

    El upsert es atómico: con varias réplicas de la API, Postgres serializa los
    incrementos de la misma fila y cada petición ve un total distinto. Va en su propia
    transacción corta, no en la de la petición: así el bloqueo de la fila dura
    microsegundos, y un lote que luego falla (422) igual cuenta para el límite.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def hit(self, station_id: UUID, window: datetime) -> int:
        async with self._engine.begin() as conn:
            count = await conn.scalar(
                text("""
                    INSERT INTO ingest.rate_limit_windows (station_id, window_start, request_count)
                    VALUES (:station_id, :window, 1)
                    ON CONFLICT (station_id, window_start)
                    DO UPDATE SET request_count = ingest.rate_limit_windows.request_count + 1
                    RETURNING request_count
                """),
                {"station_id": station_id, "window": window},
            )
        return int(count)


# Una sola sentencia: lecturas, cola y latido se escriben juntos o no se escribe nada.
# El CTE `stored` solo devuelve las filas realmente insertadas (ON CONFLICT DO NOTHING
# descarta los duplicados), así que nunca se encola una lectura que ya existía. Las
# tardías se guardan pero no se encolan: no entran en las ventanas de las reglas.
#
# El latido nunca retrocede: con dos lotes concurrentes, o un reenvío de lecturas
# antiguas, gana siempre la recepción y la medición más recientes. En DO UPDATE las
# expresiones leen la fila anterior (station_heartbeats.*), no las ya asignadas.
_STORE_AND_ENQUEUE = text("""
    WITH batch AS (
        SELECT measured_at, value, quality
        FROM unnest(
            CAST(:measured_at AS timestamptz[]),
            CAST(:value AS float8[]),
            CAST(:quality AS text[])
        ) AS t(measured_at, value, quality)
    ),
    stored AS (
        INSERT INTO ingest.readings (station_id, organization_id, measured_at, received_at,
                                     value, quality)
        SELECT :station_id, :organization_id, measured_at, :received_at, value, quality
        FROM batch
        ON CONFLICT (station_id, measured_at) DO NOTHING
        RETURNING measured_at, quality
    ),
    enqueued AS (
        INSERT INTO ingest.evaluation_queue (station_id, measured_at, organization_id,
                                             enqueued_at, available_at)
        SELECT :station_id, measured_at, :organization_id, :received_at, :received_at
        FROM stored
        WHERE quality = 'ok'
        ON CONFLICT (station_id, measured_at) DO NOTHING
        RETURNING 1
    ),
    heartbeat AS (
        INSERT INTO ingest.station_heartbeats (station_id, last_seen_at, last_measured_at,
                                               last_value, updated_at)
        SELECT :station_id, :received_at, CAST(:hb_measured_at AS timestamptz),
               CAST(:hb_value AS float8), :received_at
        WHERE CAST(:hb_measured_at AS timestamptz) IS NOT NULL  -- lote solo de tardías
        ON CONFLICT (station_id) DO UPDATE SET
            last_seen_at = GREATEST(ingest.station_heartbeats.last_seen_at,
                                    EXCLUDED.last_seen_at),
            last_value = CASE
                WHEN EXCLUDED.last_measured_at > ingest.station_heartbeats.last_measured_at
                THEN EXCLUDED.last_value
                ELSE ingest.station_heartbeats.last_value
            END,
            last_measured_at = GREATEST(ingest.station_heartbeats.last_measured_at,
                                        EXCLUDED.last_measured_at),
            updated_at = EXCLUDED.updated_at
        RETURNING 1
    )
    SELECT (SELECT count(*) FROM stored) AS stored,
           (SELECT count(*) FROM stored WHERE quality = 'late') AS late,
           (SELECT count(*) FROM enqueued) AS enqueued,
           (SELECT count(*) FROM heartbeat) AS heartbeat
""")


class SqlReadingWriter:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def store_and_enqueue(
        self,
        station_id: UUID,
        organization_id: UUID,
        readings: Sequence[ClassifiedReading],
        received_at: datetime,
        heartbeat: ClassifiedReading | None,
    ) -> StoreCounts:
        row = (
            await self._conn.execute(
                _STORE_AND_ENQUEUE,
                {
                    "station_id": station_id,
                    "organization_id": organization_id,
                    "received_at": received_at,
                    "measured_at": [r.measured_at for r in readings],
                    "value": [r.value for r in readings],
                    "quality": [r.quality.value for r in readings],
                    "hb_measured_at": heartbeat.measured_at if heartbeat else None,
                    "hb_value": heartbeat.value if heartbeat else None,
                },
            )
        ).one()
        counts = StoreCounts(stored=int(row.stored), late=int(row.late), enqueued=int(row.enqueued))
        if counts.enqueued:
            # Misma transacción que las filas: Postgres entrega el aviso solo si hace commit.
            # Sin filas nuevas en la cola no se despierta al evaluador en vano.
            await self._conn.execute(
                text("SELECT pg_notify(:channel, '')"), {"channel": notifications.EVALUATION_QUEUE}
            )
        return counts
