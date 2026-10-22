"""Requests with a wrong API key, counted per client address and minute (ADR-0011).

Counted before the key is verified, so a client that keeps sending wrong keys gets a 429
instead of an Argon2id check each time. No FK: the address belongs to no station. The silence
worker purges windows older than an hour, as it does for ingest.rate_limit_windows.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ingest.key_failure_windows (
            client_address  text NOT NULL,
            window_start    timestamptz NOT NULL,
            failure_count   integer NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
            PRIMARY KEY (client_address, window_start)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE ingest.key_failure_windows")
