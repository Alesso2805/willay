"""DispatchQueue sobre core.alerts: cada operación en su propia transacción corta."""

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from vigia.alerts.application.dispatch import ClaimedAlert
from vigia.alerts.domain.alerts import Channel
from vigia.alerts.domain.delivery import MAX_ATTEMPTS, AckToken
from vigia.alerts.domain.email import AlertMessage

# Pendientes, vencidas y con todos sus intentos gastados: el worker murió en el último
# envío sin dejar resultado. Se dan por fallidas, con su evento, en lugar de quedar
# pendientes para siempre.
_ABANDON = text("""
    WITH abandoned AS (
        UPDATE core.alerts
        SET status = 'failed', last_error = 'el envío no terminó (el worker se detuvo)'
        WHERE status = 'pending' AND channel = :channel AND next_attempt_at <= :now
          AND attempts >= :max_attempts
        RETURNING id, incident_id, contact_id, level_order, attempts
    )
    INSERT INTO core.incident_events (incident_id, organization_id, occurred_at, event_type,
                                      actor_type, payload)
    SELECT a.incident_id, i.organization_id, CAST(:now AS timestamptz), 'alert_failed',
           'system',
           jsonb_build_object('alert_id', a.id, 'contact_id', a.contact_id,
                              'channel', CAST(:channel AS text), 'level_order', a.level_order,
                              'attempt', a.attempts, 'final', true,
                              'error', 'el envío no terminó (el worker se detuvo)')
    FROM abandoned a JOIN core.incidents i ON i.id = a.incident_id
""")

# El reclamo y los datos del mensaje en una sola sentencia.
_CLAIM = text("""
    WITH due AS (
        SELECT id FROM core.alerts
        WHERE status = 'pending' AND channel = :channel AND next_attempt_at <= :now
          AND attempts < :max_attempts
        ORDER BY next_attempt_at, id
        FOR UPDATE SKIP LOCKED
        LIMIT :limit
    ), claimed AS (
        UPDATE core.alerts a
        SET attempts = a.attempts + 1, next_attempt_at = :visible_again_at
        FROM due WHERE a.id = due.id
        RETURNING a.id, a.incident_id, a.contact_id, a.level_order, a.attempts, a.destination
    )
    SELECT c.id AS alert_id, c.incident_id, i.organization_id, c.contact_id, c.level_order,
           c.attempts, c.destination, ct.full_name AS contact_name,
           o.name AS organization_name, o.timezone, z.name AS zone_name, i.severity,
           r.type AS rule_type, s.code AS station_code, s.name AS station_name, s.unit,
           i.trigger_value, i.opened_at
    FROM claimed c
    JOIN core.incidents i ON i.id = c.incident_id
    JOIN core.organizations o ON o.id = i.organization_id
    JOIN core.risk_zones z ON z.id = i.zone_id
    JOIN core.rules r ON r.id = i.rule_id
    JOIN core.contacts ct ON ct.id = c.contact_id
    LEFT JOIN core.stations s ON s.id = i.station_id
    ORDER BY c.id
""")

# `attempts = :attempt` en cada paso: si el reclamo venció y otro dispatcher la tomó, el
# resultado de este ya no cuenta.
_ATTACH_TOKEN = text("""
    UPDATE core.alerts SET ack_token_hash = :token_hash, ack_token_expires_at = :expires_at
    WHERE id = :id AND attempts = :attempt AND status = 'pending'
""")

_SENT = text("""
    WITH done AS (
        UPDATE core.alerts
        SET status = 'sent', sent_at = :now, next_attempt_at = NULL, last_error = NULL
        WHERE id = :id AND attempts = :attempt AND status = 'pending'
        RETURNING id
    )
    INSERT INTO core.incident_events (incident_id, organization_id, occurred_at, event_type,
                                      actor_type, payload)
    SELECT CAST(:incident_id AS uuid), CAST(:organization_id AS uuid),
           CAST(:now AS timestamptz), 'alert_sent', 'system', CAST(:payload AS jsonb)
    FROM done
""")

_FAILED = text("""
    WITH done AS (
        UPDATE core.alerts
        SET status = CASE WHEN :final THEN 'failed' ELSE 'pending' END,
            next_attempt_at = CAST(:retry_at AS timestamptz), last_error = :error
        WHERE id = :id AND attempts = :attempt AND status = 'pending'
        RETURNING id
    )
    INSERT INTO core.incident_events (incident_id, organization_id, occurred_at, event_type,
                                      actor_type, payload)
    SELECT CAST(:incident_id AS uuid), CAST(:organization_id AS uuid),
           CAST(:now AS timestamptz), 'alert_failed', 'system', CAST(:payload AS jsonb)
    FROM done
""")


class SqlDispatchQueue:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def claim(
        self, channel: Channel, now: datetime, visible_again_at: datetime, limit: int
    ) -> list[ClaimedAlert]:
        params = {"channel": channel.value, "now": now, "max_attempts": MAX_ATTEMPTS}
        async with self._engine.begin() as tx:
            await tx.execute(_ABANDON, params)
            rows = await tx.execute(
                _CLAIM, params | {"visible_again_at": visible_again_at, "limit": limit}
            )
            return [
                ClaimedAlert(
                    alert_id=r.alert_id,
                    incident_id=r.incident_id,
                    organization_id=r.organization_id,
                    contact_id=r.contact_id,
                    level_order=r.level_order,
                    attempt=r.attempts,
                    destination=r.destination,
                    message=AlertMessage(
                        contact_name=r.contact_name,
                        organization_name=r.organization_name,
                        timezone=r.timezone,
                        zone_name=r.zone_name,
                        severity=r.severity,
                        rule_type=r.rule_type,
                        station_code=r.station_code,
                        station_name=r.station_name,
                        unit=r.unit,
                        trigger_value=r.trigger_value,
                        opened_at=r.opened_at,
                        level_order=r.level_order,
                    ),
                )
                for r in rows
            ]

    async def attach_token(self, alert: ClaimedAlert, token: AckToken) -> bool:
        async with self._engine.begin() as tx:
            result = await tx.execute(
                _ATTACH_TOKEN,
                {
                    "id": alert.alert_id,
                    "attempt": alert.attempt,
                    "token_hash": token.token_hash,
                    "expires_at": token.expires_at,
                },
            )
        return result.rowcount == 1

    async def sent(self, alert: ClaimedAlert, now: datetime) -> None:
        async with self._engine.begin() as tx:
            await tx.execute(_SENT, self._params(alert, now, {}))

    async def failed(
        self, alert: ClaimedAlert, error: str, retry: datetime | None, now: datetime
    ) -> None:
        final = retry is None
        async with self._engine.begin() as tx:
            await tx.execute(
                _FAILED,
                self._params(alert, now, {"final": final, "error": error})
                | {"final": final, "retry_at": retry, "error": error},
            )

    @staticmethod
    def _params(alert: ClaimedAlert, now: datetime, extra: dict[str, Any]) -> dict[str, Any]:
        # Sin el destino: la línea de tiempo no guarda datos personales.
        payload = {
            "alert_id": str(alert.alert_id),
            "contact_id": str(alert.contact_id),
            "channel": "email",
            "level_order": alert.level_order,
            "attempt": alert.attempt,
        } | extra
        return {
            "id": alert.alert_id,
            "attempt": alert.attempt,
            "incident_id": alert.incident_id,
            "organization_id": alert.organization_id,
            "now": now,
            "payload": json.dumps(payload),
        }
