"""AlertRepository over core.alerts, escalation policies and contacts."""

import json
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from uuid_utils.compat import uuid7

from willay.alerts.domain.alerts import Channel, Target
from willay.shared import notifications

# Incident -> rule -> policy -> requested level -> target groups -> members. DISTINCT ON:
# a contact in two groups of the same level gets a single alert per channel. The
# organization filter is defense in depth.
_TARGETS = text("""
    SELECT DISTINCT ON (c.id, lt.channel)
           c.id AS contact_id, lt.channel,
           CASE lt.channel
               WHEN 'email' THEN c.email
               WHEN 'telegram' THEN CAST(c.telegram_chat_id AS text)
           END AS destination
    FROM core.incidents i
    JOIN core.rules r ON r.id = i.rule_id
    JOIN core.escalation_levels l ON l.policy_id = r.escalation_policy_id
                                 AND l.level_order = :level_order
    JOIN core.level_targets lt ON lt.level_id = l.id
    JOIN core.contact_group_members m ON m.group_id = lt.contact_group_id
    JOIN core.contacts c ON c.id = m.contact_id AND c.organization_id = i.organization_id
    WHERE i.id = :incident_id
    ORDER BY c.id, lt.channel
""")

_ADD = text("""
    INSERT INTO core.alerts (id, incident_id, level_order, contact_id, channel, destination,
                             status, next_attempt_at)
    VALUES (:id, :incident_id, :level_order, :contact_id, :channel, :destination,
            :status, :next_attempt_at)
""")

_SKIPPED_EVENT = text("""
    INSERT INTO core.incident_events (incident_id, organization_id, occurred_at, event_type,
                                      actor_type, payload)
    SELECT i.id, i.organization_id, :now, 'alert_skipped', 'system', CAST(:payload AS jsonb)
    FROM core.incidents i WHERE i.id = :incident_id
""")

_NOTIFY = text("SELECT pg_notify(:channel, '')")


class SqlAlertRepository:
    async def targets(
        self, tx: AsyncConnection, incident_id: UUID, level_order: int
    ) -> list[Target]:
        rows = await tx.execute(_TARGETS, {"incident_id": incident_id, "level_order": level_order})
        return [Target(r.contact_id, Channel(r.channel), r.destination) for r in rows]

    async def add(
        self,
        tx: AsyncConnection,
        incident_id: UUID,
        level_order: int,
        targets: Sequence[Target],
        now: datetime,
    ) -> None:
        if not targets:
            return
        await tx.execute(
            _ADD,
            [
                {
                    "id": uuid7(),
                    "incident_id": incident_id,
                    "level_order": level_order,
                    "contact_id": t.contact_id,
                    "channel": t.channel.value,
                    "destination": t.destination if t.reachable else None,
                    "status": t.initial_status.value,
                    # Pending right away; a skipped alert is never retried.
                    "next_attempt_at": now if t.reachable else None,
                }
                for t in targets
            ],
        )

    async def record_skipped(
        self,
        tx: AsyncConnection,
        incident_id: UUID,
        level_order: int,
        target: Target,
        reason: str,
        now: datetime,
    ) -> None:
        payload = {
            "contact_id": str(target.contact_id),
            "channel": target.channel.value,
            "level_order": level_order,
            "reason": reason,
        }
        await tx.execute(
            _SKIPPED_EVENT,
            {"incident_id": incident_id, "now": now, "payload": json.dumps(payload)},
        )

    async def wake_dispatcher(self, tx: AsyncConnection) -> None:
        await tx.execute(_NOTIFY, {"channel": notifications.ALERTS})
