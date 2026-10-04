"""Rule use cases (VIG-27). Operator and admin manage them, audited in the same transaction
and scoped to the actor's organization (another organization's rule, zone, station or policy
does not exist).

A rule is never deleted: incidents point to it and its timeline must keep making sense, so
DELETE deactivates and a PUT with `is_active` reactivates. Its type never changes either: the
params mean something different per type. Edits apply from the next reading or silence
cycle; incidents already open carry on.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from uuid_utils.compat import uuid7

from willay.rules.application.actor import Actor
from willay.rules.domain.rules import InvalidRuleError, RuleData, RuleType, checked
from willay.shared.audit import AuditEntry, AuditLog
from willay.shared.clock import Clock
from willay.shared.errors import ErrorCode

ENTITY_TYPE = "rule"


@dataclass(frozen=True)
class Ref:
    id: UUID
    name: str


@dataclass(frozen=True)
class StationRef:
    id: UUID
    code: str
    name: str
    unit: str  # the params' value and delta are in this unit


@dataclass(frozen=True)
class Rule:
    id: UUID
    type: RuleType
    data: RuleData
    zone: Ref
    station: StationRef | None
    policy: Ref
    created_at: datetime
    updated_at: datetime

    def snapshot(self) -> dict[str, Any]:
        """What the audit log stores, readable as it was then."""
        return {
            "type": self.type.value,
            "zone": self.zone.name,
            "station": self.station.code if self.station is not None else None,
            "params": dict(self.data.params),
            "severity": self.data.severity.value,
            "escalation_policy": self.policy.name,
            "cooldown_s": self.data.cooldown_s,
            "is_active": self.data.is_active,
        }


class RuleNotFoundError(Exception):
    pass


class RuleRepository(Protocol):
    async def all_of(self, organization_id: UUID, *, include_inactive: bool) -> list[Rule]:
        """By zone, then type and station."""
        ...

    async def get(
        self, organization_id: UUID, rule_id: UUID, *, for_update: bool = False
    ) -> Rule | None: ...

    async def zone_exists(self, organization_id: UUID, zone_id: UUID) -> bool: ...

    async def station_in_zone(
        self, organization_id: UUID, station_id: UUID, zone_id: UUID
    ) -> bool: ...

    async def policy_exists(self, organization_id: UUID, policy_id: UUID) -> bool: ...

    async def add(
        self,
        rule_id: UUID,
        organization_id: UUID,
        rule_type: RuleType,
        data: RuleData,
        created_by: UUID,
        now: datetime,
    ) -> Rule: ...

    async def replace(
        self, organization_id: UUID, rule_id: UUID, data: RuleData, now: datetime
    ) -> Rule: ...


async def create_rule(
    actor: Actor,
    rule_type: RuleType,
    data: RuleData,
    *,
    rules: RuleRepository,
    audit: AuditLog,
    clock: Clock,
) -> Rule:
    data = await _check(actor, rule_type, data, rules)
    now = clock.now()
    rule = await rules.add(uuid7(), actor.organization_id, rule_type, data, actor.user_id, now)
    await audit.record(_entry(actor, rule.id, "create", None, rule, now))
    return rule


async def update_rule(
    actor: Actor,
    rule_id: UUID,
    rule_type: RuleType,
    data: RuleData,
    *,
    rules: RuleRepository,
    audit: AuditLog,
    clock: Clock,
) -> Rule:
    current = await _locked(actor, rule_id, rules)
    if rule_type is not current.type:
        raise InvalidRuleError("type", ErrorCode.RULE_TYPE_FIXED)
    data = await _check(actor, rule_type, data, rules)
    if data == current.data:
        return current  # no changes: no write and no empty audit entry
    now = clock.now()
    updated = await rules.replace(actor.organization_id, rule_id, data, now)
    await audit.record(_entry(actor, rule_id, "update", current, updated, now))
    return updated


async def deactivate_rule(
    actor: Actor, rule_id: UUID, *, rules: RuleRepository, audit: AuditLog, clock: Clock
) -> None:
    current = await _locked(actor, rule_id, rules)
    if not current.data.is_active:
        return
    now = clock.now()
    inactive = replace(current.data, is_active=False)
    updated = await rules.replace(actor.organization_id, rule_id, inactive, now)
    await audit.record(_entry(actor, rule_id, "deactivate", current, updated, now))


async def _check(
    actor: Actor, rule_type: RuleType, data: RuleData, rules: RuleRepository
) -> RuleData:
    data = checked(rule_type, data)
    org = actor.organization_id
    if not await rules.zone_exists(org, data.zone_id):
        raise InvalidRuleError("zone_id", ErrorCode.RULE_ZONE_UNKNOWN)
    # Only stations of the zone: the evaluator joins zone_stations, so any other would never fire.
    if data.station_id is not None and not await rules.station_in_zone(
        org, data.station_id, data.zone_id
    ):
        raise InvalidRuleError("station_id", ErrorCode.RULE_STATION_OUTSIDE_ZONE)
    if not await rules.policy_exists(org, data.escalation_policy_id):
        raise InvalidRuleError("escalation_policy_id", ErrorCode.RULE_POLICY_UNKNOWN)
    return data


async def _locked(actor: Actor, rule_id: UUID, rules: RuleRepository) -> Rule:
    # FOR UPDATE: two operators editing the same rule don't clobber the audited "before".
    rule = await rules.get(actor.organization_id, rule_id, for_update=True)
    if rule is None:
        raise RuleNotFoundError(rule_id)
    return rule


def _entry(
    actor: Actor,
    rule_id: UUID,
    action: str,
    before: Rule | None,
    after: Rule | None,
    at: datetime,
) -> AuditEntry:
    return AuditEntry(
        organization_id=actor.organization_id,
        actor_id=actor.user_id,
        entity_type=ENTITY_TYPE,
        entity_id=rule_id,
        action=action,
        before=before.snapshot() if before is not None else None,
        after=after.snapshot() if after is not None else None,
        at=at,
    )
