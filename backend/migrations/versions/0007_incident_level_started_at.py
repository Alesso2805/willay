"""incidents.level_started_at: cuándo se avisó al nivel de escalamiento actual.

El `wait_s` de cada nivel cuenta desde que se le avisó (SPEC). Sin esta columna habría
que deducirlo sumando los `wait_s` desde la apertura, y un nivel que escala al instante
por no tener envíos le quitaría tiempo al siguiente.

Mismo patrón que la 0004: se agrega nullable, se rellena (para los incidentes que ya
existen, el nivel 1 empezó al abrirse) y después se exige NOT NULL.

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
    # El worker escalation solo mira incidentes abiertos que aún pueden escalar.
    op.execute("""
        CREATE INDEX incidents_escalation_idx ON core.incidents (level_started_at)
        WHERE status = 'open' AND escalation_exhausted_at IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX core.incidents_escalation_idx")
    op.execute("ALTER TABLE core.incidents DROP COLUMN level_started_at")
