"""Un solo evento station_recovered por incidente.

El worker silence registra station_recovered cuando una estación silenciada vuelve a
reportar. Con dos workers a la vez, "insertar si no existe" tiene carrera: ambos ven que
no existe e insertan. Igual que con los incidentes activos, la unicidad la garantiza
Postgres con un índice único parcial y el worker inserta con ON CONFLICT DO NOTHING.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE UNIQUE INDEX incident_events_one_recovery
        ON core.incident_events (incident_id)
        WHERE event_type = 'station_recovered'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX core.incident_events_one_recovery")
