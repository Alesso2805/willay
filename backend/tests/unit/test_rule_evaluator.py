from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncConnection

from tests.support.alerts import FakeAlerting
from tests.support.incidents import FakeIncidentStore
from vigia.incidents.domain.incidents import EvidenceReading, Worsening
from vigia.rules.application.queue import QueuedReading
from vigia.rules.application.rule_evaluator import ApplicableRule, RuleEvaluator
from vigia.shared.clock import FakeClock

T0 = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
TX = cast(AsyncConnection, object())
ITEM = QueuedReading(1, uuid4(), uuid4(), T0, 1)


def _rule(rule_type: str = "threshold", **params: Any) -> ApplicableRule:
    params = params or {"operator": "gt", "value": 3.5, "consecutive": 2}
    return ApplicableRule(
        uuid4(), ITEM.organization_id, uuid4(), rule_type, params, "critical", cooldown_s=600
    )


class Rules:
    def __init__(self, *rules: ApplicableRule) -> None:
        self.rules = list(rules)

    async def applicable(
        self, tx: Any, organization_id: UUID, station_id: UUID
    ) -> list[ApplicableRule]:
        return self.rules


class History:
    def __init__(self, *values: float) -> None:
        # Latest first, like the real query.
        self.readings = [
            EvidenceReading(T0 - timedelta(seconds=10 * i), v) for i, v in enumerate(values)
        ]
        self.limits: list[int] = []
        self.windows: list[tuple[datetime, datetime]] = []

    async def latest_ok(
        self, tx: Any, station_id: UUID, until: datetime, limit: int
    ) -> list[EvidenceReading]:
        self.limits.append(limit)
        return self.readings[:limit]

    async def ok_between(
        self, tx: Any, station_id: UUID, since: datetime, until: datetime
    ) -> list[EvidenceReading]:
        self.windows.append((since, until))
        return list(reversed(self.readings))  # chronological


async def _evaluate(rule: ApplicableRule, incidents: FakeIncidentStore, *values: float) -> None:
    """Evaluates the reading against this history (latest first)."""
    await RuleEvaluator(
        Rules(rule), History(*values), incidents, FakeClock(T0), alerts=FakeAlerting()
    ).evaluate(TX, ITEM)


async def test_a_firing_threshold_opens_an_incident_with_its_evidence() -> None:
    rule, incidents, history = _rule(), FakeIncidentStore(), History(3.7, 3.6, 1.0)
    await RuleEvaluator(
        Rules(rule), history, incidents, FakeClock(T0), alerts=FakeAlerting()
    ).evaluate(TX, ITEM)

    [trigger] = incidents.opened
    assert trigger.dedup_key == f"{rule.id}:{rule.zone_id}"
    assert trigger.trigger_value == 3.7
    assert [r.value for r in trigger.evidence] == [3.6, 3.7]  # chronological
    assert history.limits == [2]  # asks only for the N readings it needs


async def test_nothing_is_opened_when_the_rule_does_not_fire() -> None:
    incidents = FakeIncidentStore()
    await RuleEvaluator(
        Rules(_rule()), History(3.7, 3.4), incidents, FakeClock(T0), alerts=FakeAlerting()
    ).evaluate(TX, ITEM)
    assert incidents.opened == []


async def test_a_sudden_drop_opens_an_incident_with_the_whole_window_as_evidence() -> None:
    rule = _rule("rate_of_change", direction="down", delta=40.0, window_minutes=10)
    incidents, history = FakeIncidentStore(), History(60.0, 34.0, 85.0, 84.0)  # latest first
    await RuleEvaluator(
        Rules(rule), history, incidents, FakeClock(T0), alerts=FakeAlerting()
    ).evaluate(TX, ITEM)

    [trigger] = incidents.opened
    assert trigger.trigger_value == 34.0  # the reading that completed the drop
    assert [r.value for r in trigger.evidence] == [84.0, 85.0, 34.0, 60.0]
    # The window ends at the evaluated reading, not at the clock.
    assert history.windows == [(T0 - timedelta(minutes=10), T0)]


async def test_a_change_within_delta_opens_nothing() -> None:
    rule = _rule("rate_of_change", direction="down", delta=40.0, window_minutes=10)
    incidents = FakeIncidentStore()
    await RuleEvaluator(
        Rules(rule), History(50.0, 85.0), incidents, FakeClock(T0), alerts=FakeAlerting()
    ).evaluate(TX, ITEM)
    assert incidents.opened == []


async def test_a_broken_rule_is_skipped_and_the_next_one_still_runs() -> None:
    broken, good, incidents = _rule(operator="between"), _rule(), FakeIncidentStore()
    await RuleEvaluator(
        Rules(broken, good), History(4.0, 4.0), incidents, FakeClock(T0), alerts=FakeAlerting()
    ).evaluate(TX, ITEM)
    assert [t.rule_id for t in incidents.opened] == [good.id]


async def test_the_trigger_carries_the_rule_cooldown_and_how_it_worsens() -> None:
    incidents = FakeIncidentStore()
    await _evaluate(_rule(), incidents, 3.7, 3.6)
    [trigger] = incidents.opened
    assert (trigger.cooldown_s, trigger.worsening) == (600, Worsening.HIGHER)


async def test_an_active_threshold_incident_adds_only_readings_that_worsen_it() -> None:
    rule, incidents = _rule(), FakeIncidentStore()
    await _evaluate(rule, incidents, 3.7, 3.6)  # opens at 3.7
    await _evaluate(rule, incidents, 3.9, 3.7)  # new maximum: added
    await _evaluate(rule, incidents, 3.8, 3.9)  # still out of bounds but not worse
    await _evaluate(rule, incidents, 3.9, 3.8)  # ties the worst value, which is not worse

    assert len(incidents.opened) == 1
    assert [r.value for r in incidents.added] == [3.9]


async def test_a_lower_limit_worsens_downwards() -> None:
    rule, incidents = _rule(operator="lt", value=0.5, consecutive=1), FakeIncidentStore()
    await _evaluate(rule, incidents, 0.4)
    await _evaluate(rule, incidents, 0.45)  # still below the limit, but better
    await _evaluate(rule, incidents, 0.3)
    assert [r.value for r in incidents.added] == [0.3]


async def test_a_drop_worsens_with_a_lower_valley() -> None:
    rule = _rule("rate_of_change", direction="down", delta=40.0, window_minutes=10)
    incidents = FakeIncidentStore()
    await _evaluate(rule, incidents, 34.0, 85.0)  # opens at the valley of 34
    await _evaluate(rule, incidents, 30.0, 34.0, 85.0)  # the drop deepens
    assert [r.value for r in incidents.added] == [30.0]


async def test_nothing_is_opened_while_the_cause_cools_down() -> None:
    incidents = FakeIncidentStore(cooling_down=True)
    await _evaluate(_rule(), incidents, 3.7, 3.6)
    assert (incidents.opened, incidents.added) == ([], [])
