"""DispatchQueue over core.alerts: each operation in its own short transaction."""

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from willay.alerts.application.dispatch import ClaimedAlert
from willay.alerts.domain.alerts import Channel, Reason
from willay.alerts.domain.delivery import MAX_ATTEMPTS, AckToken
from willay.alerts.infrastructure.alert_messages import (
    MESSAGE_COLUMNS,
    MESSAGE_JOINS,
    message_from_row,
)

# Pending alerts of an incident no longer open are skipped with their event, including
# those claimed by another dispatcher (its result no longer counts: it requires `pending`).
_CANCEL = text("""
    WITH cancelled AS (
        UPDATE core.alerts a
        SET status = 'skipped', next_attempt_at = NULL
        FROM core.incidents i
        WHERE i.id = a.incident_id AND a.status = 'pending' AND a.channel = :channel
          AND i.status <> 'open'
        RETURNING a.id, a.incident_id, a.contact_id, a.level_order, i.organization_id,
                  i.status AS incident_status
    )
    INSERT INTO core.incident_events (incident_id, organization_id, occurred_at, event_type,
                                      actor_type, payload)
    SELECT c.incident_id, c.organization_id, CAST(:now AS timestamptz), 'alert_skipped',
           'system',
           jsonb_build_object('alert_id', c.id, 'contact_id', c.contact_id,
                              'channel', CAST(:channel AS text), 'level_order', c.level_order,
                              'reason_code', CASE c.incident_status
                                                 WHEN 'acknowledged'
                                                 THEN CAST(:skip_acknowledged AS text)
                                                 ELSE CAST(:skip_resolved AS text) END)
    FROM cancelled c
""")

# Pending, due and out of attempts: the worker died during the last send without a
# result. Marked failed, with their event, instead of staying pending forever.
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

_CLAIM = text(f"""
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
    SELECT a.id AS alert_id, a.incident_id, i.organization_id, a.contact_id, a.attempts,
           a.destination, i.correlation_id, i.trigger_received_at, {MESSAGE_COLUMNS}
    FROM claimed a
    {MESSAGE_JOINS}
    ORDER BY a.id
""")

# `attempts = :attempt` at every step: if the claim expired and another dispatcher took
# the alert, this one's result no longer counts.
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
    -- Whether no other alert of the incident was sent before: the latency metric's first.
    RETURNING NOT EXISTS (
        SELECT 1 FROM core.alerts o
        WHERE o.incident_id = CAST(:incident_id AS uuid) AND o.id <> CAST(:id AS uuid)
          AND o.sent_at IS NOT NULL
    ) AS first
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
            await tx.execute(
                _CANCEL,
                params
                | {
                    "skip_acknowledged": Reason.INCIDENT_ACKNOWLEDGED.value,
                    "skip_resolved": Reason.INCIDENT_RESOLVED.value,
                },
            )
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
                    message=message_from_row(r),
                    channel=channel,
                    correlation_id=r.correlation_id,
                    trigger_received_at=r.trigger_received_at,
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

    async def sent(self, alert: ClaimedAlert, now: datetime) -> bool:
        async with self._engine.begin() as tx:
            first = await tx.scalar(_SENT, self._params(alert, now, {}))
        return bool(first)  # None: the claim was no longer ours, nothing was recorded

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
        # No destination: the timeline never stores personal data.
        payload = {
            "alert_id": str(alert.alert_id),
            "contact_id": str(alert.contact_id),
            "channel": alert.channel.value,
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
