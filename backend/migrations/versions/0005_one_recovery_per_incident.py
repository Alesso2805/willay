"""A single station_recovered event per incident.

The silence worker records station_recovered when a silenced station reports again. With two
workers, "insert if absent" races (both see nothing and insert). As with active incidents,
Postgres guarantees uniqueness with a partial unique index and the worker inserts with
ON CONFLICT DO NOTHING.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE UNIQUE INDEX incident_events_one_recovery
        ON core.incident_events (incident_id)
        WHERE event_type = 'station_recovered'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX core.incident_events_one_recovery")
