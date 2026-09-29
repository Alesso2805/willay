"""alerts.destination solo puede faltar en una alerta omitida.

Si el contacto no tiene el canal del nivel (sin correo, o Telegram sin vincular), la
alerta se registra como `skipped` (SPEC: canal faltante) y no tiene destino. Guardar una
cadena vacía escondería el caso; con NULL y un CHECK, Postgres garantiza que toda alerta
que se va a enviar tiene a dónde.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE core.alerts ALTER COLUMN destination DROP NOT NULL")
    op.execute("""
        ALTER TABLE core.alerts ADD CONSTRAINT alerts_destination_check
            CHECK (status = 'skipped' OR destination IS NOT NULL)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE core.alerts DROP CONSTRAINT alerts_destination_check")
    op.execute("UPDATE core.alerts SET destination = '' WHERE destination IS NULL")
    op.execute("ALTER TABLE core.alerts ALTER COLUMN destination SET NOT NULL")
