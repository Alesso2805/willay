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
        return list(reversed(self.readings))  # cronológico


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


async def test_a_sudden_drop_opens_an_incident_with_the_whole_window_as_evidence() -> None:
    rule = _rule("rate_of_change", direction="down", delta=40.0, window_minutes=10)
    incidents, history = Incidents(), History(60.0, 34.0, 85.0, 84.0)  # la última primero
    await RuleEvaluator(Rules(rule), history, incidents, FakeClock(T0)).evaluate(TX, ITEM)

    [trigger] = incidents.opened
    assert trigger.trigger_value == 34.0  # la lectura que completó la caída
    assert [r.value for r in trigger.evidence] == [84.0, 85.0, 34.0, 60.0]
    # La ventana termina en la lectura evaluada, no en el reloj.
    assert history.windows == [(T0 - timedelta(minutes=10), T0)]


async def test_a_change_within_delta_opens_nothing() -> None:
    rule = _rule("rate_of_change", direction="down", delta=40.0, window_minutes=10)
    incidents = Incidents()
    await RuleEvaluator(Rules(rule), History(50.0, 85.0), incidents, FakeClock(T0)).evaluate(
        TX, ITEM
    )
    assert incidents.opened == []


async def test_a_broken_rule_is_skipped_and_the_next_one_still_runs() -> None:
    broken, good, incidents = _rule(operator="between"), _rule(), Incidents()
    await RuleEvaluator(Rules(broken, good), History(4.0, 4.0), incidents, FakeClock(T0)).evaluate(
        TX, ITEM
    )
    assert [t.rule_id for t in incidents.opened] == [good.id]
