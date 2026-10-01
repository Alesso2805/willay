"""IncidentStore over core.incidents and core.incident_events."""

import json
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from uuid_utils.compat import uuid7

from willay.incidents.application.open_incident import OpenResult, OpenStatus, Trigger
from willay.incidents.application.station_recovery import Recovery
from willay.incidents.domain.incidents import EvidenceReading

# One statement for both opening rules:
# - cooldown: nothing is inserted if the same cause was resolved after :cooling_since;
# - dedup: ON CONFLICT with the partial unique index predicate (migration 0002). If an
#   incident with that cause is active, nothing is inserted and RETURNING yields no rows.
#   Postgres guarantees it, even with two concurrent evaluators.
# With INSERT ... SELECT the parameters do not take the column type: hence the CASTs.
_OPEN = text("""
    INSERT INTO core.incidents (id, organization_id, zone_id, rule_id, station_id, severity,
                                trigger_value, dedup_key, opened_at, level_started_at)
    SELECT CAST(:id AS uuid), CAST(:organization_id AS uuid), CAST(:zone_id AS uuid),
           CAST(:rule_id AS uuid), CAST(:station_id AS uuid), CAST(:severity AS text),
           CAST(:trigger_value AS double precision), CAST(:dedup_key AS text),
           CAST(:now AS timestamptz), CAST(:now AS timestamptz)
    WHERE NOT EXISTS (
        SELECT 1 FROM core.incidents
        WHERE dedup_key = CAST(:dedup_key AS text) AND status = 'resolved'
          AND resolved_at > CAST(:cooling_since AS timestamptz)
    )
    ON CONFLICT (dedup_key) WHERE status IN ('open', 'acknowledged') DO NOTHING
    RETURNING id
""")

_ACTIVE = text("""
    SELECT id FROM core.incidents
    WHERE dedup_key = :dedup_key AND status IN ('open', 'acknowledged')
""")

_OPENED_EVENT = text("""
    INSERT INTO core.incident_events (incident_id, organization_id, occurred_at, event_type,
                                      actor_type, payload)
    VALUES (:incident_id, :organization_id, :now, 'opened', 'system', CAST(:payload AS jsonb))
""")

# Partial unique index from migration 0005: one station_recovered per incident, even if
# two silence workers detect it at once. Needs INSERT only: willay_app cannot modify events
# (append-only).
_RECOVERED_EVENT = text("""
    INSERT INTO core.incident_events (incident_id, organization_id, occurred_at, event_type,
                                      actor_type, payload)
    VALUES (:incident_id, :organization_id, :now, 'station_recovered', 'system',
            CAST(:payload AS jsonb))
    ON CONFLICT (incident_id) WHERE event_type = 'station_recovered' DO NOTHING
    RETURNING id
""")

# FOR UPDATE on the incident serializes two evaluators worsening it at once. Since a
# reading_added is only recorded when it worsens, the last one recorded is the worst.
_LOCK_INCIDENT = text("SELECT trigger_value FROM core.incidents WHERE id = :id FOR UPDATE")
_LAST_ADDED = text("""
    SELECT CAST(payload->>'value' AS double precision) FROM core.incident_events
    WHERE incident_id = :id AND event_type = 'reading_added'
    ORDER BY id DESC
    LIMIT 1
""")

_READING_ADDED_EVENT = text("""
    INSERT INTO core.incident_events (incident_id, organization_id, occurred_at, event_type,
                                      actor_type, payload)
    VALUES (:incident_id, :organization_id, :now, 'reading_added', 'system',
            CAST(:payload AS jsonb))
""")


class SqlIncidentStore:
    async def open(self, tx: AsyncConnection, trigger: Trigger, now: datetime) -> OpenResult:
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
                "cooling_since": now - timedelta(seconds=trigger.cooldown_s),
            },
        )
        if not isinstance(incident_id, UUID):
            # Either one is active or the cause is cooling down. If it was resolved right
            # between the two queries, none is active and it counts as cooldown: it just closed.
            active = await tx.scalar(_ACTIVE, {"dedup_key": trigger.dedup_key})
            if isinstance(active, UUID):
                return OpenResult(OpenStatus.ACTIVE, active)
            return OpenResult(OpenStatus.COOLING_DOWN, None)
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
        return OpenResult(OpenStatus.OPENED, incident_id)

    async def worst_value(self, tx: AsyncConnection, incident_id: UUID) -> float | None:
        trigger_value = await tx.scalar(_LOCK_INCIDENT, {"id": incident_id})
        last_added = await tx.scalar(_LAST_ADDED, {"id": incident_id})
        worst = last_added if last_added is not None else trigger_value
        return float(worst) if worst is not None else None

    async def add_reading(
        self,
        tx: AsyncConnection,
        incident_id: UUID,
        organization_id: UUID,
        reading: EvidenceReading,
        now: datetime,
    ) -> None:
        payload = {"measured_at": reading.measured_at.isoformat(), "value": reading.value}
        await tx.execute(
            _READING_ADDED_EVENT,
            {
                "incident_id": incident_id,
                "organization_id": organization_id,
                "now": now,
                "payload": json.dumps(payload),
            },
        )

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
