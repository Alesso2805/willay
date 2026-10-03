"""A correlation id from the reading to the alert (VIG-28).

Each accepted batch gets one; it travels with its queue rows and stays on the incident it
opens, so the logs of ingestion, evaluation and every alert of that incident share it (SPEC:
trace a demo incident using only the logs). Silence incidents get their own. Rows written
before this migration have none.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE ingest.evaluation_queue ADD COLUMN correlation_id uuid")
    op.execute("ALTER TABLE core.incidents ADD COLUMN correlation_id uuid")


def downgrade() -> None:
    op.execute("ALTER TABLE core.incidents DROP COLUMN correlation_id")
    op.execute("ALTER TABLE ingest.evaluation_queue DROP COLUMN correlation_id")
