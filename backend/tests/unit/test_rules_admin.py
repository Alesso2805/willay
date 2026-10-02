"""VIG-27: rule validation and use cases, with an in-memory repository."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from willay.incidents.domain.severity import Severity
from willay.rules.application.actor import Actor
from willay.rules.application.rules import (
    Ref,
    Rule,
    RuleNotFoundError,
    StationRef,
    create_rule,
    deactivate_rule,
    update_rule,
)
from willay.rules.domain.rules import (
    MAX_COOLDOWN_S,
    InvalidRuleError,
    RuleData,
    RuleType,
    canonical_params,
    checked,
)
from willay.shared.audit import AuditEntry
from willay.shared.clock import FakeClock

T0 = datetime(2026, 12, 22, 9, 0, tzinfo=UTC)
ACTOR = Actor(uuid4(), uuid4())
CHOSICA = Ref(uuid4(), "Chosica")
QUIRIO = StationRef(uuid4(), "RIM-QUI-01", "Quebrada Quirio", "mm")
POLICY = Ref(uuid4(), "Protocolo Rímac")
GT_20 = {"operator": "gt", "value": 20, "consecutive": 3}


def _data(**changes: Any) -> RuleData:
    base = RuleData(
        zone_id=CHOSICA.id,
        station_id=QUIRIO.id,
        params=GT_20,
        severity=Severity.WARNING,
        escalation_policy_id=POLICY.id,
        cooldown_s=3600,
        is_active=True,
    )
    return replace(base, **changes)


class FakeRules:
    def __init__(self, *rules: Rule) -> None:
        self.by_id = {r.id: r for r in rules}
        self.writes = 0

    async def all_of(self, organization_id: UUID, *, include_inactive: bool) -> list[Rule]:
        return list(self.by_id.values())

    async def get(
        self, organization_id: UUID, rule_id: UUID, *, for_update: bool = False
    ) -> Rule | None:
        return self.by_id.get(rule_id) if organization_id == ACTOR.organization_id else None

    async def zone_exists(self, organization_id: UUID, zone_id: UUID) -> bool:
        return zone_id == CHOSICA.id

    async def station_in_zone(self, organization_id: UUID, station_id: UUID, zone_id: UUID) -> bool:
        return (station_id, zone_id) == (QUIRIO.id, CHOSICA.id)

    async def policy_exists(self, organization_id: UUID, policy_id: UUID) -> bool:
        return policy_id == POLICY.id

    async def add(
        self,
        rule_id: UUID,
        organization_id: UUID,
        rule_type: RuleType,
        data: RuleData,
        created_by: UUID,
        now: datetime,
    ) -> Rule:
        self.writes += 1
        self.by_id[rule_id] = _rule(rule_id, rule_type, data)
        return self.by_id[rule_id]

    async def replace(
        self, organization_id: UUID, rule_id: UUID, data: RuleData, now: datetime
    ) -> Rule:
        self.writes += 1
        self.by_id[rule_id] = _rule(rule_id, self.by_id[rule_id].type, data)
        return self.by_id[rule_id]


class FakeAudit:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


def _rule(rule_id: UUID, rule_type: RuleType, data: RuleData) -> Rule:
    station = QUIRIO if data.station_id == QUIRIO.id else None
    return Rule(rule_id, rule_type, data, CHOSICA, station, POLICY, T0, T0)


def test_params_are_stored_as_the_evaluator_reads_them() -> None:
    assert canonical_params(RuleType.THRESHOLD, GT_20) == {
        "operator": "gt",
        "value": 20.0,
        "consecutive": 3,
    }
    rate = {"direction": "down", "delta": 40, "window_minutes": 10}
    assert canonical_params(RuleType.RATE_OF_CHANGE, rate)["delta"] == 40.0
    assert canonical_params(RuleType.SILENCE, {}) == {}


@pytest.mark.parametrize(
    ("rule_type", "data", "field"),
    [
        # A value is compared in a station's unit: a zone-wide threshold would mix units.
        (RuleType.THRESHOLD, _data(station_id=None), "station_id"),
        (RuleType.RATE_OF_CHANGE, _data(station_id=None), "station_id"),
        (RuleType.THRESHOLD, _data(params={"operator": "gt", "value": 1}), "params"),
        (RuleType.THRESHOLD, _data(params={**GT_20, "consecutive": 61}), "params"),
        (RuleType.SILENCE, _data(params={"multiplier": 5}), "params"),  # K is the station's
        (RuleType.THRESHOLD, _data(cooldown_s=MAX_COOLDOWN_S + 1), "cooldown_s"),
    ],
)
def test_an_invalid_rule_names_its_field(rule_type: RuleType, data: RuleData, field: str) -> None:
    with pytest.raises(InvalidRuleError) as caught:
        checked(rule_type, data)
    assert caught.value.field == field


def test_silence_may_watch_a_whole_zone() -> None:
    assert checked(RuleType.SILENCE, _data(station_id=None, params={})).station_id is None


async def test_creating_records_the_rule_readably() -> None:
    rules, audit = FakeRules(), FakeAudit()
    rule = await create_rule(
        ACTOR, RuleType.THRESHOLD, _data(), rules=rules, audit=audit, clock=FakeClock(T0)
    )
    [entry] = audit.entries
    assert (entry.entity_type, entry.entity_id, entry.action, entry.before) == (
        "rule",
        rule.id,
        "create",
        None,
    )
    assert entry.after == {
        "type": "threshold",
        "zone": "Chosica",
        "station": "RIM-QUI-01",
        "params": {"operator": "gt", "value": 20.0, "consecutive": 3},
        "severity": "warning",
        "escalation_policy": "Protocolo Rímac",
        "cooldown_s": 3600,
        "is_active": True,
    }


@pytest.mark.parametrize(
    ("data", "field"),
    [
        (_data(zone_id=uuid4()), "zone_id"),
        (_data(station_id=uuid4()), "station_id"),  # not a station of that zone
        (_data(escalation_policy_id=uuid4()), "escalation_policy_id"),
    ],
)
async def test_what_a_rule_points_to_must_be_the_organizations(data: RuleData, field: str) -> None:
    rules, audit = FakeRules(), FakeAudit()
    with pytest.raises(InvalidRuleError) as caught:
        await create_rule(
            ACTOR, RuleType.THRESHOLD, data, rules=rules, audit=audit, clock=FakeClock(T0)
        )
    assert caught.value.field == field
    assert (rules.writes, audit.entries) == (0, [])


async def test_the_type_never_changes() -> None:
    rule = _rule(uuid4(), RuleType.THRESHOLD, checked(RuleType.THRESHOLD, _data()))
    rules, audit = FakeRules(rule), FakeAudit()
    with pytest.raises(InvalidRuleError) as caught:
        await update_rule(
            ACTOR, rule.id, RuleType.SILENCE, _data(params={}),
            rules=rules, audit=audit, clock=FakeClock(T0),
        )  # fmt: skip
    assert caught.value.field == "type"


async def test_an_edit_that_changes_nothing_writes_nothing() -> None:
    rule = _rule(uuid4(), RuleType.THRESHOLD, checked(RuleType.THRESHOLD, _data()))
    rules, audit = FakeRules(rule), FakeAudit()
    # The same params written differently (20 instead of 20.0) are the same rule.
    same = await update_rule(
        ACTOR, rule.id, RuleType.THRESHOLD, _data(), rules=rules, audit=audit, clock=FakeClock(T0)
    )
    assert same == rule
    assert (rules.writes, audit.entries) == (0, [])


async def test_deactivating_is_audited_once() -> None:
    rule = _rule(uuid4(), RuleType.THRESHOLD, checked(RuleType.THRESHOLD, _data()))
    rules, audit = FakeRules(rule), FakeAudit()
    for _ in range(2):
        await deactivate_rule(ACTOR, rule.id, rules=rules, audit=audit, clock=FakeClock(T0))
    assert rules.by_id[rule.id].data.is_active is False
    assert [(e.action, e.before["is_active"], e.after["is_active"]) for e in audit.entries] == [  # type: ignore[index]
        ("deactivate", True, False)
    ]


async def test_another_organizations_rule_does_not_exist() -> None:
    rule = _rule(uuid4(), RuleType.THRESHOLD, checked(RuleType.THRESHOLD, _data()))
    rules, audit = FakeRules(rule), FakeAudit()
    stranger = Actor(uuid4(), uuid4())
    with pytest.raises(RuleNotFoundError):
        await deactivate_rule(stranger, rule.id, rules=rules, audit=audit, clock=FakeClock(T0))
