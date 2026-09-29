"""IncidentStore sobre core.incidents y core.incident_events."""

import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from uuid_utils.compat import uuid7

from vigia.incidents.application.open_incident import Trigger

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
