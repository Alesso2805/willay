"""core and ingest schemas and default privileges for vigia_app.

First on purpose: with ALTER DEFAULT PRIVILEGES set before any table exists, every table (from
0002, 0003 and any future migration) grants vigia_app access the same way, with no manual GRANT.

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
    op.execute("GRANT USAGE ON SCHEMA core, ingest TO vigia_app")

    # FOR ROLE vigia_owner: applies to objects created by vigia_owner, which runs the
    # migrations. Without it every new table would need its own GRANT.
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE vigia_owner IN SCHEMA core, ingest "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO vigia_app"
    )
    # Identity columns (incident_events, audit_log, evaluation_queue) use sequences.
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE vigia_owner IN SCHEMA core, ingest "
        "GRANT USAGE, SELECT ON SEQUENCES TO vigia_app"
    )


def downgrade() -> None:
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE vigia_owner IN SCHEMA core, ingest "
        "REVOKE USAGE, SELECT ON SEQUENCES FROM vigia_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE vigia_owner IN SCHEMA core, ingest "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM vigia_app"
    )
    op.execute("DROP SCHEMA ingest")
    op.execute("DROP SCHEMA core")
