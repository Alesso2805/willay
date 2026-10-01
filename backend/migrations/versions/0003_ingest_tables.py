"""ingest schema tables (4) and the readings hypertable.

- readings: hypertable on measured_at (1-day chunks), columnstore (compression) after 7 days
  and 180-day retention (ADR-0003).
- No FK points to readings: TimescaleDB restricts FKs to hypertables. evaluation_queue
  stores (station_id, measured_at) without an FK.

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
            -- The PK includes the partition column (a Timescale requirement) and makes a
            -- duplicate reading by (station_id, measured_at) get ignored.
            PRIMARY KEY (station_id, measured_at)
        )
    """)
    op.execute(
        "SELECT create_hypertable('ingest.readings', by_range('measured_at', INTERVAL '1 day'))"
    )
    # segmentby station_id: queries are "one station's readings in a window", so each station
    # gets its own compressed segment, ordered by time.
    op.execute("""
        ALTER TABLE ingest.readings SET (
            timescaledb.enable_columnstore = true,
            timescaledb.segmentby = 'station_id',
            timescaledb.orderby = 'measured_at DESC'
        )
    """)
    op.execute("CALL add_columnstore_policy('ingest.readings', after => INTERVAL '7 days')")
    op.execute("SELECT add_retention_policy('ingest.readings', drop_after => INTERVAL '180 days')")
    # Checks the NFR "zero ok readings without evaluated_at after 120 s".
    op.execute("""
        CREATE INDEX readings_pending_evaluation_idx
            ON ingest.readings (received_at) WHERE quality = 'ok' AND evaluated_at IS NULL
    """)

    op.execute("""
        CREATE TABLE ingest.evaluation_queue (
            id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            station_id       uuid NOT NULL REFERENCES core.stations (id),
            measured_at      timestamptz NOT NULL,  -- no FK to readings (hypertable)
            organization_id  uuid NOT NULL,
            enqueued_at      timestamptz NOT NULL,
            available_at     timestamptz NOT NULL,  -- 60 s visibility timeout
            attempts         integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            last_error       text,
            failed_at        timestamptz,
            -- Re-enqueuing the same reading does not create a second row.
            UNIQUE (station_id, measured_at)
        )
    """)
    # Live rows only: rows that reached failed_at leave the index the evaluator uses.
    op.execute("""
        CREATE INDEX evaluation_queue_available_idx
            ON ingest.evaluation_queue (available_at) WHERE failed_at IS NULL
    """)

    op.execute("""
        CREATE TABLE ingest.station_heartbeats (
            station_id    uuid PRIMARY KEY REFERENCES core.stations (id) ON DELETE CASCADE,
            last_seen_at  timestamptz NOT NULL,  -- received_at of the latest non-late reading
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
    # Dropping the hypertable also drops its chunks and policies.
    op.execute("DROP TABLE ingest.readings")
