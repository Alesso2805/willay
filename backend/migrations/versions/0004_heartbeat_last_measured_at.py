"""station_heartbeats.last_measured_at: cuándo se midió last_value.

Sin esta columna no se sabe la antigüedad del último valor (la necesita el mapa) ni se
puede evitar que un lote concurrente o un reenvío antiguo lo pise con uno más viejo.

Patrón para columnas obligatorias en tablas que pueden tener filas: añadir nullable,
rellenar y después exigir NOT NULL. Añadir directamente NOT NULL sin DEFAULT falla si
la tabla no está vacía.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE ingest.station_heartbeats ADD COLUMN last_measured_at timestamptz")
    # Mejor aproximación disponible para filas previas: el momento en que se recibió.
    op.execute("UPDATE ingest.station_heartbeats SET last_measured_at = last_seen_at")
    op.execute("ALTER TABLE ingest.station_heartbeats ALTER COLUMN last_measured_at SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE ingest.station_heartbeats DROP COLUMN last_measured_at")
