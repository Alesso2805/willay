from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncConnection

from vigia.incidents.application.open_incident import Trigger
from vigia.incidents.domain.incidents import EvidenceReading
from vigia.rules.application.queue import QueuedReading
from vigia.rules.application.rule_evaluator import ApplicableRule, RuleEvaluator
from vigia.shared.clock import FakeClock

T0 = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
TX = cast(AsyncConnection, object())
ITEM = QueuedReading(1, uuid4(), uuid4(), T0, 1)


def _rule(rule_type: str = "threshold", **params: Any) -> ApplicableRule:
    params = params or {"operator": "gt", "value": 3.5, "consecutive": 2}
    return ApplicableRule(uuid4(), ITEM.organization_id, uuid4(), rule_type, params, "critical")


class Rules:
    def __init__(self, *rules: ApplicableRule) -> None:
        self.rules = list(rules)

    async def applicable(
        self, tx: Any, organization_id: UUID, station_id: UUID
    ) -> list[ApplicableRule]:
        return self.rules


class History:
    def __init__(self, *values: float) -> None:
        # La última primero, como la consulta real.
        self.readings = [
            EvidenceReading(T0 - timedelta(seconds=10 * i), v) for i, v in enumerate(values)
        ]
        self.limits: list[int] = []

    async def latest_ok(
        self, tx: Any, station_id: UUID, until: datetime, limit: int
    ) -> list[EvidenceReading]:
        self.limits.append(limit)
        return self.readings[:limit]


class Incidents:
    def __init__(self) -> None:
        self.opened: list[Trigger] = []

    async def open(self, tx: Any, trigger: Trigger, now: datetime) -> UUID | None:
        self.opened.append(trigger)
        return uuid4()


async def test_a_firing_threshold_opens_an_incident_with_its_evidence() -> None:
    rule, incidents, history = _rule(), Incidents(), History(3.7, 3.6, 1.0)
    await RuleEvaluator(Rules(rule), history, incidents, FakeClock(T0)).evaluate(TX, ITEM)

    [trigger] = incidents.opened
    assert trigger.dedup_key == f"{rule.id}:{rule.zone_id}"
    assert trigger.trigger_value == 3.7
    assert [r.value for r in trigger.evidence] == [3.6, 3.7]  # cronológico
    assert history.limits == [2]  # pide solo las N lecturas que necesita


async def test_nothing_is_opened_when_the_rule_does_not_fire() -> None:
    incidents = Incidents()
    await RuleEvaluator(Rules(_rule()), History(3.7, 3.4), incidents, FakeClock(T0)).evaluate(
        TX, ITEM
    )
    assert incidents.opened == []


async def test_rate_of_change_rules_are_ignored_until_vig_16() -> None:
    incidents = Incidents()
    rule = _rule("rate_of_change", direction="down", delta=40.0, window_minutes=10)
    await RuleEvaluator(Rules(rule), History(9.0, 9.0), incidents, FakeClock(T0)).evaluate(TX, ITEM)
    assert incidents.opened == []


async def test_a_broken_rule_is_skipped_and_the_next_one_still_runs() -> None:
    broken, good, incidents = _rule(operator="between"), _rule(), Incidents()
    await RuleEvaluator(Rules(broken, good), History(4.0, 4.0), incidents, FakeClock(T0)).evaluate(
        TX, ITEM
    )
    assert [t.rule_id for t in incidents.opened] == [good.id]
