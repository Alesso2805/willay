"""station_heartbeats.last_measured_at: when last_value was measured.

Without it the map cannot show the age of the last value, and a concurrent batch or an old
resend could overwrite it with an older one.

Pattern for required columns on tables that may have rows: add nullable, backfill, then set
NOT NULL. Adding NOT NULL without a DEFAULT directly fails on a non-empty table.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE ingest.station_heartbeats ADD COLUMN last_measured_at timestamptz")
    # Best available approximation for existing rows: when it was received.
    op.execute("UPDATE ingest.station_heartbeats SET last_measured_at = last_seen_at")
    op.execute("ALTER TABLE ingest.station_heartbeats ALTER COLUMN last_measured_at SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE ingest.station_heartbeats DROP COLUMN last_measured_at")
