"""Tablas del esquema ingest (4) y hypertable de lecturas.

- readings: hypertable por measured_at (chunks de 1 día), columnstore (compresión)
  a los 7 días y retención de 180 días (ADR-0003).
- Nada apunta con FK a readings: TimescaleDB restringe las FK hacia hypertables.
  evaluation_queue guarda (station_id, measured_at) sin FK.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ingest.readings (
            station_id       uuid NOT NULL REFERENCES core.stations (id),
            organization_id  uuid NOT NULL,
            measured_at      timestamptz NOT NULL,
            received_at      timestamptz NOT NULL,
            value            double precision NOT NULL,
            quality          text NOT NULL CHECK (quality IN ('ok', 'late')),
            evaluated_at     timestamptz,
            -- La PK incluye la columna de partición (requisito de Timescale) y hace
            -- que una lectura duplicada por (station_id, measured_at) se ignore.
            PRIMARY KEY (station_id, measured_at)
        )
    """)
    op.execute(
        "SELECT create_hypertable('ingest.readings', by_range('measured_at', INTERVAL '1 day'))"
    )
    # segmentby station_id: las consultas son "lecturas de una estación en una ventana",
    # así cada estación queda en su propio segmento comprimido, ordenado por tiempo.
    op.execute("""
        ALTER TABLE ingest.readings SET (
            timescaledb.enable_columnstore = true,
            timescaledb.segmentby = 'station_id',
            timescaledb.orderby = 'measured_at DESC'
        )
    """)
    op.execute("CALL add_columnstore_policy('ingest.readings', after => INTERVAL '7 days')")
    op.execute("SELECT add_retention_policy('ingest.readings', drop_after => INTERVAL '180 days')")
    # Verificación de la NFR "cero lecturas ok sin evaluated_at pasados 120 s".
    op.execute("""
        CREATE INDEX readings_pending_evaluation_idx
            ON ingest.readings (received_at) WHERE quality = 'ok' AND evaluated_at IS NULL
    """)

    op.execute("""
        CREATE TABLE ingest.evaluation_queue (
            id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            station_id       uuid NOT NULL REFERENCES core.stations (id),
            measured_at      timestamptz NOT NULL,  -- sin FK a readings (hypertable)
            organization_id  uuid NOT NULL,
            enqueued_at      timestamptz NOT NULL,
            available_at     timestamptz NOT NULL,  -- visibility timeout de 60 s
            attempts         integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            last_error       text,
            failed_at        timestamptz,
            -- Reencolar la misma lectura no crea una segunda fila.
            UNIQUE (station_id, measured_at)
        )
    """)
    # Solo las filas vivas: las que llegaron a failed_at salen del índice que usa el evaluador.
    op.execute("""
        CREATE INDEX evaluation_queue_available_idx
            ON ingest.evaluation_queue (available_at) WHERE failed_at IS NULL
    """)

    op.execute("""
        CREATE TABLE ingest.station_heartbeats (
            station_id    uuid PRIMARY KEY REFERENCES core.stations (id) ON DELETE CASCADE,
            last_seen_at  timestamptz NOT NULL,  -- received_at de la última lectura no tardía
            last_value    double precision,
            updated_at    timestamptz NOT NULL
        )
    """)

    op.execute("""
        CREATE TABLE ingest.rate_limit_windows (
            station_id     uuid NOT NULL REFERENCES core.stations (id) ON DELETE CASCADE,
            window_start   timestamptz NOT NULL,
            request_count  integer NOT NULL DEFAULT 0 CHECK (request_count >= 0),
            PRIMARY KEY (station_id, window_start)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE ingest.rate_limit_windows")
    op.execute("DROP TABLE ingest.station_heartbeats")
    op.execute("DROP TABLE ingest.evaluation_queue")
    # Borrar la hypertable elimina también sus chunks y sus políticas.
    op.execute("DROP TABLE ingest.readings")
