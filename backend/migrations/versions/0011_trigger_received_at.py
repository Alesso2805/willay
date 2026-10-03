"""When the reading that opened an incident arrived (VIG-28).

The latency SPEC measures, received_to_alert_seconds, runs from that moment to the incident's
first alert sent. The reading itself may expire (retention), so the incident keeps the
instant. Silence incidents have none: no reading opens them.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE core.incidents ADD COLUMN trigger_received_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE core.incidents DROP COLUMN trigger_received_at")
