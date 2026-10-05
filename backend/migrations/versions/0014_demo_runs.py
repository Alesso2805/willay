"""The public demo's runs (VIG-43): the Rímac scenario a visitor asks for, and the nightly restore.

A queue in Postgres like the others (ADR-0002): the API inserts a run, the demo worker takes it,
plays it and closes it. The partial unique index keeps one run at a time per organization, so a
second visitor pressing the button gets a 409 instead of a second scenario on top of the first.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE core.demo_runs (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES core.organizations (id),
            kind text NOT NULL CONSTRAINT demo_runs_kind_check
                CHECK (kind IN ('scenario', 'restore')),
            requested_by uuid REFERENCES core.users (id),
            requested_at timestamptz NOT NULL,
            started_at timestamptz,
            finished_at timestamptz,
            outcome text CONSTRAINT demo_runs_outcome_check CHECK (outcome IN ('done', 'failed')),
            error text,
            CONSTRAINT demo_runs_finished_check
                CHECK ((finished_at IS NULL) = (outcome IS NULL))
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX demo_runs_one_active ON core.demo_runs (organization_id)
        WHERE finished_at IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP TABLE core.demo_runs")
