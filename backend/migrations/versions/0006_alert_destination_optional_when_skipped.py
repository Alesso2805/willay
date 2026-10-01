"""alerts.destination may be missing only on a skipped alert.

If the contact lacks the level's channel (no email, or Telegram not linked), the alert is
recorded as `skipped` (SPEC: missing channel) with no destination. An empty string would hide
that case; with NULL plus a CHECK, Postgres guarantees every alert to be sent has a destination.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE core.alerts ALTER COLUMN destination DROP NOT NULL")
    op.execute("""
        ALTER TABLE core.alerts ADD CONSTRAINT alerts_destination_check
            CHECK (status = 'skipped' OR destination IS NOT NULL)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE core.alerts DROP CONSTRAINT alerts_destination_check")
    op.execute("UPDATE core.alerts SET destination = '' WHERE destination IS NULL")
    op.execute("ALTER TABLE core.alerts ALTER COLUMN destination SET NOT NULL")
