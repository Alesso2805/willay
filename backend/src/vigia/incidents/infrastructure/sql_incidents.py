"""IncidentStore sobre core.incidents y core.incident_events."""

import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from uuid_utils.compat import uuid7

from vigia.incidents.application.open_incident import Trigger
from vigia.incidents.application.station_recovery import Recovery

# ON CONFLICT con el predicado del índice único parcial (migración 0002): si ya existe un
# incidente activo con esa causa, no se inserta nada y RETURNING no devuelve filas. La
# deduplicación la garantiza Postgres, también con dos evaluadores a la vez.
_OPEN = text("""
    INSERT INTO core.incidents (id, organization_id, zone_id, rule_id, station_id, severity,
                                trigger_value, dedup_key, opened_at)
    VALUES (:id, :organization_id, :zone_id, :rule_id, :station_id, :severity,
            :trigger_value, :dedup_key, :now)
    ON CONFLICT (dedup_key) WHERE status IN ('open', 'acknowledged') DO NOTHING
    RETURNING id
""")

_OPENED_EVENT = text("""
    INSERT INTO core.incident_events (incident_id, organization_id, occurred_at, event_type,
                                      actor_type, payload)
    VALUES (:incident_id, :organization_id, :now, 'opened', 'system', CAST(:payload AS jsonb))
""")

# Índice único parcial de la migración 0005: un solo station_recovered por incidente,
# aunque dos workers silence lo detecten a la vez. Solo necesita INSERT: vigia_app no
# puede modificar eventos (append-only).
_RECOVERED_EVENT = text("""
    INSERT INTO core.incident_events (incident_id, organization_id, occurred_at, event_type,
                                      actor_type, payload)
    VALUES (:incident_id, :organization_id, :now, 'station_recovered', 'system',
            CAST(:payload AS jsonb))
    ON CONFLICT (incident_id) WHERE event_type = 'station_recovered' DO NOTHING
    RETURNING id
""")


class SqlIncidentStore:
    async def open(self, tx: AsyncConnection, trigger: Trigger, now: datetime) -> UUID | None:
        incident_id = await tx.scalar(
            _OPEN,
            {
                "id": uuid7(),
                "organization_id": trigger.organization_id,
                "zone_id": trigger.zone_id,
                "rule_id": trigger.rule_id,
                "station_id": trigger.station_id,
                "severity": trigger.severity,
                "trigger_value": trigger.trigger_value,
                "dedup_key": trigger.dedup_key,
                "now": now,
            },
        )
        if not isinstance(incident_id, UUID):
            return None
        payload = {
            "rule_type": trigger.rule_type,
            "rule_params": dict(trigger.rule_params),
            "station_id": str(trigger.station_id),
            "trigger_value": trigger.trigger_value,
            "readings": [
                {"measured_at": r.measured_at.isoformat(), "value": r.value}
                for r in trigger.evidence
            ],
            "details": dict(trigger.details),
        }
        await tx.execute(
            _OPENED_EVENT,
            {
                "incident_id": incident_id,
                "organization_id": trigger.organization_id,
                "now": now,
                "payload": json.dumps(payload),
            },
        )
        return incident_id

    async def record_recovery(self, tx: AsyncConnection, recovery: Recovery, now: datetime) -> bool:
        payload = {
            "station_id": str(recovery.station_id),
            "last_seen_at": recovery.last_seen_at.isoformat(),
            "last_measured_at": (
                recovery.last_measured_at.isoformat() if recovery.last_measured_at else None
            ),
            "last_value": recovery.last_value,
        }
        event_id = await tx.scalar(
            _RECOVERED_EVENT,
            {
                "incident_id": recovery.incident_id,
                "organization_id": recovery.organization_id,
                "now": now,
                "payload": json.dumps(payload),
            },
        )
        return event_id is not None
