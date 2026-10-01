"""core and ingest schemas and default privileges for willay_app.

First on purpose: with ALTER DEFAULT PRIVILEGES set before any table exists, every table (from
0002, 0003 and any future migration) grants willay_app access the same way, with no manual GRANT.

Extensions and roles are created by infra/postgres/init (ADR-0005). CREATE EXTENSION IF NOT
EXISTS here only checks they exist: if missing it fails on permissions and the migrate container
exits with an error, which is what we want.

Revision ID: 0001
Revises:
Create Date: 2026-09-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.execute("CREATE SCHEMA core")
    op.execute("CREATE SCHEMA ingest")
    op.execute("REVOKE ALL ON SCHEMA core, ingest FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA core, ingest TO willay_app")

    # FOR ROLE willay_owner: applies to objects created by willay_owner, which runs the
    # migrations. Without it every new table would need its own GRANT.
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE willay_owner IN SCHEMA core, ingest "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO willay_app"
    )
    # Identity columns (incident_events, audit_log, evaluation_queue) use sequences.
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE willay_owner IN SCHEMA core, ingest "
        "GRANT USAGE, SELECT ON SEQUENCES TO willay_app"
    )


def downgrade() -> None:
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE willay_owner IN SCHEMA core, ingest "
        "REVOKE USAGE, SELECT ON SEQUENCES FROM willay_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE willay_owner IN SCHEMA core, ingest "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM willay_app"
    )
    op.execute("DROP SCHEMA ingest")
    op.execute("DROP SCHEMA core")
