"""The language of each contact's alerts, and the organization's as the default (VIG-40).

Emails, Telegram messages and the confirmation page speak the contact's language; a contact
without one (NULL) gets the organization's, which is Spanish unless set otherwise.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE core.organizations ADD COLUMN language text NOT NULL DEFAULT 'es'"
        " CONSTRAINT organizations_language_check CHECK (language IN ('es', 'en'))"
    )
    op.execute(
        "ALTER TABLE core.contacts ADD COLUMN language text"
        " CONSTRAINT contacts_language_check CHECK (language IN ('es', 'en'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE core.contacts DROP COLUMN language")
    op.execute("ALTER TABLE core.organizations DROP COLUMN language")
