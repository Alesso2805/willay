from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.support.alerts import FakeAlerting
from tests.support.incidents import FakeIncidentStore
from willay.alerts.application.planning import AlertPlanner, LevelAlerts
from willay.alerts.domain.alerts import AlertStatus, Channel, Reason, Target
from willay.incidents.domain.incidents import EvidenceReading
from willay.rules.application.queue import QueuedReading
from willay.rules.application.rule_evaluator import ApplicableRule, RuleEvaluator
from willay.shared.clock import FakeClock

T0 = datetime(2026, 11, 20, 14, 0, tzinfo=UTC)
INCIDENT = uuid4()
TX = cast(AsyncConnection, object())


@pytest.mark.parametrize(
    ("destination", "status"),
    [
        ("operador@rimac.willay.test", AlertStatus.PENDING),
        (None, AlertStatus.SKIPPED),
        ("   ", AlertStatus.SKIPPED),  # a blank email is not a destination
    ],
)
def test_a_target_without_its_channel_is_skipped(
    destination: str | None, status: AlertStatus
) -> None:
    assert Target(uuid4(), Channel.EMAIL, destination).initial_status is status


class Repository:
    def __init__(self, *targets: Target) -> None:
        self._targets = list(targets)
        self.added: list[Target] = []
        self.skipped: list[tuple[Target, str]] = []
        self.woken = 0

    async def targets(self, tx: Any, incident_id: UUID, level_order: int) -> list[Target]:
        return self._targets

    async def add(
        self,
        tx: Any,
        incident_id: UUID,
        level_order: int,
        targets: Sequence[Target],
        now: datetime,
    ) -> None:
        self.added.extend(targets)

    async def record_skipped(
        self,
        tx: Any,
        incident_id: UUID,
        level_order: int,
        target: Target,
        reason: str,
        now: datetime,
    ) -> None:
        self.skipped.append((target, reason))

    async def wake_dispatcher(self, tx: Any) -> None:
        self.woken += 1


async def test_every_target_gets_an_alert_and_the_unreachable_are_recorded() -> None:
    email = Target(uuid4(), Channel.EMAIL, "operador@rimac.willay.test")
    no_email = Target(uuid4(), Channel.EMAIL, None)
    no_telegram = Target(uuid4(), Channel.TELEGRAM, None)
    repository = Repository(email, no_email, no_telegram)

    result = await AlertPlanner(repository).alert_level(TX, INCIDENT, 1, T0)

    assert result == LevelAlerts(pending=1, skipped=2)
    assert repository.added == [email, no_email, no_telegram]
    assert repository.skipped == [
        (no_email, Reason.NO_EMAIL),
        (no_telegram, Reason.NO_TELEGRAM),
    ]
    assert repository.woken == 1


async def test_the_dispatcher_is_not_woken_when_nothing_can_be_sent() -> None:
    repository = Repository(Target(uuid4(), Channel.EMAIL, None))
    result = await AlertPlanner(repository).alert_level(TX, INCIDENT, 1, T0)
    assert (result, repository.woken) == (LevelAlerts(pending=0, skipped=1), 0)


class Rules:
    def __init__(self, rule: ApplicableRule) -> None:
        self.rule = rule

    async def applicable(self, tx: Any, organization_id: UUID, station_id: UUID) -> list[Any]:
        return [self.rule]


class History:
    def __init__(self, *latest_first: float) -> None:
        self.values = latest_first

    async def latest_ok(self, tx: Any, station_id: UUID, until: datetime, limit: int) -> list[Any]:
        return [EvidenceReading(T0, v) for v in self.values[:limit]]

    async def ok_between(self, *args: Any) -> list[Any]:
        return []


async def test_only_opening_an_incident_alerts_its_first_level() -> None:
    item = QueuedReading(1, uuid4(), uuid4(), T0, 1)
    rule = ApplicableRule(
        uuid4(),
        item.organization_id,
        uuid4(),
        "threshold",
        {"operator": "gt", "value": 3.5, "consecutive": 1},
        "critical",
        cooldown_s=600,
    )
    incidents, alerting = FakeIncidentStore(), FakeAlerting()

    for value in (3.7, 3.9, 3.8):  # opens, worsens, unchanged
        evaluator = RuleEvaluator(
            Rules(rule), History(value), incidents, FakeClock(T0), alerts=alerting
        )
        await evaluator.evaluate(TX, item)

    assert [level for _, level in alerting.levels] == [1]
