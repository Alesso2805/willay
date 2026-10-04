"""The language each user chose for the dashboard (VIG-40).

NULL until they choose one: meanwhile the dashboard follows the browser's language, and
Spanish when the browser's is not offered. Saved in the database, not in the browser, so the
choice follows the user to any device.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE core.users ADD COLUMN language text"
        " CONSTRAINT users_language_check CHECK (language IN ('es', 'en'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE core.users DROP COLUMN language")
