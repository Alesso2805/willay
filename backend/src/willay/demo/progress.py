"""What the demo reads from the database, as willay_app: checks before it starts and the
story's progress while it runs."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from willay.demo.story import IncidentState, StoryEvent

_RULES = text("""
    SELECT r.id, r.is_active, r.escalation_policy_id, s.code
    FROM core.rules r LEFT JOIN core.stations s ON s.id = r.station_id
    WHERE r.id = ANY(CAST(:rule_ids AS uuid[]))
""")

_LEVELS = text("""
    SELECT level_order, wait_s FROM core.escalation_levels
    WHERE policy_id = :policy_id ORDER BY level_order
""")

# Names only: whether a chat is linked is all the demo needs, never the chat_id itself.
_TELEGRAM_AT_LEVEL = text("""
    SELECT DISTINCT c.full_name
    FROM core.escalation_levels l
    JOIN core.level_targets t ON t.level_id = l.id AND t.channel = 'telegram'
    JOIN core.contact_group_members m ON m.group_id = t.contact_group_id
    JOIN core.contacts c ON c.id = m.contact_id
    WHERE l.policy_id = :policy_id AND l.level_order = :level_order
      AND c.telegram_chat_id IS NOT NULL
    ORDER BY c.full_name
""")

# The same names as the dashboard's timeline (incidents_repository._TIMELINE), plus the
# station, the rule and, for a contact's acknowledgement, the channel of the alert they used.
_EVENTS = text("""
    SELECT e.id, e.incident_id, i.rule_id, e.occurred_at, e.event_type, e.actor_type,
           e.payload, COALESCE(u.full_name, ac.full_name) AS actor_name,
           rc.full_name AS contact_name, s.code AS station_code,
           (SELECT a.channel FROM core.alerts a
            WHERE e.event_type = 'acknowledged' AND e.actor_type = 'contact'
              AND a.incident_id = e.incident_id AND a.contact_id = e.actor_id
              AND a.status = 'acknowledged'
            ORDER BY a.acknowledged_at LIMIT 1) AS acknowledged_channel
    FROM core.incident_events e
    JOIN core.incidents i ON i.id = e.incident_id
    LEFT JOIN core.stations s ON s.id = i.station_id
    LEFT JOIN core.users u
           ON e.actor_type = 'user' AND u.id = e.actor_id
          AND u.organization_id = e.organization_id
    LEFT JOIN core.contacts ac
           ON e.actor_type = 'contact' AND ac.id = e.actor_id
          AND ac.organization_id = e.organization_id
    LEFT JOIN core.contacts rc
           ON CAST(rc.id AS text) = e.payload->>'contact_id'
          AND rc.organization_id = e.organization_id
    WHERE e.organization_id = :organization_id AND e.occurred_at >= :since
    ORDER BY e.occurred_at, e.id
""")

# The first incident per rule since the run started: the clean slate leaves no older ones.
_INCIDENTS = text("""
    SELECT DISTINCT ON (rule_id) id, rule_id, status, current_level,
           acknowledged_at IS NOT NULL AS acknowledged,
           escalation_exhausted_at IS NOT NULL AS exhausted
    FROM core.incidents
    WHERE organization_id = :organization_id AND rule_id = ANY(CAST(:rule_ids AS uuid[]))
      AND opened_at >= :since
    ORDER BY rule_id, opened_at
""")


@dataclass(frozen=True)
class DemoRule:
    id: UUID
    active: bool
    policy_id: UUID
    station_code: str | None


@dataclass(frozen=True)
class Readiness:
    rules: list[DemoRule]
    levels: list[tuple[int, int]]  # (level_order, wait_s) of the first rule's policy
    telegram_at_ack_level: list[str]  # who can acknowledge from Telegram at that level


async def readiness(conn: AsyncConnection, rule_ids: Sequence[UUID], ack_level: int) -> Readiness:
    rows = (await conn.execute(_RULES, {"rule_ids": list(rule_ids)})).all()
    by_id = {r.id: DemoRule(r.id, r.is_active, r.escalation_policy_id, r.code) for r in rows}
    rules = [by_id[rule_id] for rule_id in rule_ids if rule_id in by_id]
    if not rules:
        return Readiness([], [], [])
    policy_id = rules[0].policy_id
    levels = [
        (r.level_order, r.wait_s) for r in await conn.execute(_LEVELS, {"policy_id": policy_id})
    ]
    names = await conn.scalars(
        _TELEGRAM_AT_LEVEL, {"policy_id": policy_id, "level_order": ack_level}
    )
    return Readiness(rules, levels, list(names))


async def events(conn: AsyncConnection, organization_id: UUID, since: datetime) -> list[StoryEvent]:
    rows = await conn.execute(_EVENTS, {"organization_id": organization_id, "since": since})
    return [
        StoryEvent(
            id=r.id,
            incident_id=r.incident_id,
            rule_id=r.rule_id,
            occurred_at=r.occurred_at,
            event_type=r.event_type,
            actor_type=r.actor_type,
            payload=r.payload if isinstance(r.payload, dict) else json.loads(r.payload),
            actor_name=r.actor_name,
            contact_name=r.contact_name,
            station_code=r.station_code,
            acknowledged_channel=r.acknowledged_channel,
        )
        for r in rows
    ]


async def incidents(
    conn: AsyncConnection, organization_id: UUID, rule_ids: Sequence[UUID], since: datetime
) -> dict[UUID, IncidentState]:
    params = {"organization_id": organization_id, "rule_ids": list(rule_ids), "since": since}
    rows = await conn.execute(_INCIDENTS, params)
    return {
        r.rule_id: IncidentState(
            r.id, r.rule_id, r.status, r.current_level, r.acknowledged, r.exhausted
        )
        for r in rows
    }
