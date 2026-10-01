"""incidents.level_started_at: when the current escalation level was notified.

Each level's `wait_s` counts from when it was notified (SPEC). Without this column it would be
derived by summing `wait_s` from opening, and a level that escalates instantly (nothing sent)
would steal time from the next one.

Same pattern as 0004: add nullable, backfill (for existing incidents level 1 started at
opening), then set NOT NULL.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE core.incidents ADD COLUMN level_started_at timestamptz")
    op.execute("UPDATE core.incidents SET level_started_at = opened_at")
    op.execute("ALTER TABLE core.incidents ALTER COLUMN level_started_at SET NOT NULL")
    # The escalation worker only looks at open incidents that can still escalate.
    op.execute("""
        CREATE INDEX incidents_escalation_idx ON core.incidents (level_started_at)
        WHERE status = 'open' AND escalation_exhausted_at IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX core.incidents_escalation_idx")
    op.execute("ALTER TABLE core.incidents DROP COLUMN level_started_at")
