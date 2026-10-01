"""Avisos en tiempo real: NOTIFY vigia_events desde la base (VIG-25, ADR-0007).

Un trigger avisa cada vez que se registra un evento de incidente o cambia el latido de
una estación. Así ningún camino de código (los de hoy y los que vengan) puede olvidarse
de avisar al panel, y el aviso sale en la misma transacción: Postgres solo lo entrega si
la transacción confirma.

El aviso lleva lo justo para enrutarlo (la organización) y para que el panel sepa qué
refrescar. Nunca datos personales: el detalle lo pide el panel por REST, con sus permisos.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION core.notify_incident_event() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_notify('vigia_events', json_build_object(
                'organization_id', NEW.organization_id,
                'type', 'incident',
                'incident_id', NEW.incident_id,
                'event', NEW.event_type
            )::text);
            RETURN NULL;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER incident_events_notify
        AFTER INSERT ON core.incident_events
        FOR EACH ROW EXECUTE FUNCTION core.notify_incident_event()
    """)
    # station_heartbeats no guarda la organización: se busca en stations (por su PK).
    op.execute("""
        CREATE FUNCTION ingest.notify_heartbeat() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_notify('vigia_events', json_build_object(
                'organization_id', (SELECT s.organization_id FROM core.stations s
                                    WHERE s.id = NEW.station_id),
                'type', 'station',
                'station_id', NEW.station_id,
                'last_seen_at', NEW.last_seen_at,
                'last_measured_at', NEW.last_measured_at,
                'last_value', NEW.last_value
            )::text);
            RETURN NULL;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER station_heartbeats_notify
        AFTER INSERT OR UPDATE ON ingest.station_heartbeats
        FOR EACH ROW EXECUTE FUNCTION ingest.notify_heartbeat()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER station_heartbeats_notify ON ingest.station_heartbeats")
    op.execute("DROP FUNCTION ingest.notify_heartbeat()")
    op.execute("DROP TRIGGER incident_events_notify ON core.incident_events")
    op.execute("DROP FUNCTION core.notify_incident_event()")
