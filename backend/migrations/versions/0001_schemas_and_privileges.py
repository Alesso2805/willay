"""Esquemas core e ingest y privilegios por defecto para vigia_app.

Va primero a propósito: con ALTER DEFAULT PRIVILEGES fijado antes de crear tablas,
todas (las de 0002, 0003 y cualquier migración futura) reciben permisos para
vigia_app por el mismo mecanismo, sin GRANT manuales.

Las extensiones y los roles los crea infra/postgres/init (ADR-0005). Aquí
CREATE EXTENSION IF NOT EXISTS solo comprueba que estén: si faltan, falla por
permisos y el contenedor migrate termina con error, que es lo que queremos.

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

    # FOR ROLE vigia_owner: aplica a los objetos que cree vigia_owner, que es quien
    # corre las migraciones. Sin esto, cada tabla nueva necesitaría su propio GRANT.
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE vigia_owner IN SCHEMA core, ingest "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO vigia_app"
    )
    # Las columnas identity (incident_events, audit_log, evaluation_queue) usan secuencias.
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
