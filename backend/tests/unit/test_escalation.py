from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.support.alerts import FakeAlerting
from willay.alerts.application.escalation import EscalationCycle, Escalator
from willay.alerts.domain.alerts import Reason
from willay.alerts.domain.escalation import Decision, LevelState, Step, decide
from willay.shared.clock import FakeClock

T0 = datetime(2026, 11, 20, 14, 0, tzinfo=UTC)  # when the current level was alerted
INCIDENT = uuid4()
DEMO_POLICY = {1: 120, 2: 180, 3: 300}  # the Rímac policy in the seed


def _state(**kw: Any) -> LevelState:
    defaults: dict[str, Any] = {
        "current_level": 1,
        "level_started_at": T0,
        "wait_s": 120,
        "next_level": 2,
        "nobody_alerted": False,
    }
    return LevelState(**(defaults | kw))


@pytest.mark.parametrize(
    ("state", "now", "decision"),
    [
        (_state(), T0 + timedelta(seconds=119), Decision(Step.WAIT)),
        (
            _state(),
            T0 + timedelta(seconds=120),
            Decision(Step.ESCALATE, Reason.NOT_ACKNOWLEDGED, {"wait_s": 120}),
        ),
        (
            _state(current_level=3, wait_s=300, next_level=None),
            T0 + timedelta(seconds=300),
            Decision(Step.EXHAUST, Reason.NOT_ACKNOWLEDGED, {"wait_s": 300}),
        ),
        (  # nothing was sent: the level expires at once
            _state(nobody_alerted=True),
            T0,
            Decision(Step.ESCALATE, Reason.LEVEL_REACHED_NOBODY, {"level": 1}),
        ),
        (  # an admin removed the level while the incident was escalating
            _state(current_level=2, wait_s=None, next_level=None),
            T0,
            Decision(Step.EXHAUST, Reason.LEVEL_REMOVED, {"level": 2}),
        ),
    ],
)
def test_when_a_level_expires(state: LevelState, now: datetime, decision: Decision) -> None:
    assert decide(state, now) == decision


class Incident:
    """An open in-memory incident under the demo policy."""

    def __init__(self, alerting: FakeAlerting, policy: dict[int, int] = DEMO_POLICY) -> None:
        self.alerting, self.policy = alerting, policy
        self.level, self.started = 1, T0
        self.open = True
        self.exhausted_at: datetime | None = None
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def due(self, tx: Any, now: datetime, limit: int) -> list[UUID]:
        return [INCIDENT]

    async def lock(self, tx: Any, incident_id: UUID) -> LevelState | None:
        if not self.open or self.exhausted_at is not None:
            return None  # acknowledged, resolved or exhausted
        return LevelState(
            current_level=self.level,
            level_started_at=self.started,
            wait_s=self.policy.get(self.level),
            next_level=min((n for n in self.policy if n > self.level), default=None),
            nobody_alerted=self.level in self.alerting.unreachable,
        )

    async def move_to_level(self, tx: Any, incident_id: UUID, level: int, now: datetime) -> None:
        self.level, self.started = level, now

    async def exhaust(self, tx: Any, incident_id: UUID, now: datetime) -> None:
        self.exhausted_at = now

    async def record(
        self, tx: Any, incident_id: UUID, event_type: str, payload: dict[str, Any], now: datetime
    ) -> None:
        self.events.append((event_type, payload))


@asynccontextmanager
async def _transaction() -> AsyncIterator[AsyncConnection]:
    yield cast(AsyncConnection, object())


def _escalator(incident: Incident, clock: FakeClock) -> Escalator:
    return Escalator(incident, incident.alerting, clock, _transaction)


async def test_the_next_level_is_alerted_once_the_wait_is_over() -> None:
    alerting = FakeAlerting()
    incident, clock = Incident(alerting), FakeClock(T0 + timedelta(seconds=119))
    escalator = _escalator(incident, clock)

    assert await escalator.run() == EscalationCycle(escalated=0, exhausted=0)
    clock.advance(timedelta(seconds=1))
    assert await escalator.run() == EscalationCycle(escalated=1, exhausted=0)

    assert (incident.level, incident.started) == (2, clock.now())  # its wait starts now
    assert alerting.levels == [(INCIDENT, 2)]
    assert incident.events == [
        (
            "escalated",
            {
                "from_level": 1,
                "to_level": 2,
                "reason_code": Reason.NOT_ACKNOWLEDGED,
                "reason_params": {"wait_s": 120},
            },
        )
    ]


async def test_a_level_that_reaches_nobody_is_skipped_in_the_same_cycle() -> None:
    alerting = FakeAlerting(unreachable=frozenset({2}))
    incident = Incident(alerting)
    cycle = await _escalator(incident, FakeClock(T0 + timedelta(seconds=120))).run()

    assert cycle == EscalationCycle(escalated=2, exhausted=0)
    assert incident.level == 3
    assert [(p["reason_code"], p["reason_params"]) for _, p in incident.events] == [
        (Reason.NOT_ACKNOWLEDGED, {"wait_s": 120}),
        (Reason.LEVEL_REACHED_NOBODY, {"level": 2}),
    ]


async def test_the_last_level_exhausts_the_policy_once() -> None:
    alerting = FakeAlerting()
    incident, clock = Incident(alerting), FakeClock(T0)
    escalator = _escalator(incident, clock)
    for wait in (120, 180, 300):
        clock.advance(timedelta(seconds=wait))
        await escalator.run()

    assert incident.exhausted_at == clock.now()
    assert incident.events[-1] == (
        "escalation_exhausted",
        {"level": 3, "reason_code": Reason.NOT_ACKNOWLEDGED, "reason_params": {"wait_s": 300}},
    )
    clock.advance(timedelta(hours=1))
    assert await escalator.run() == EscalationCycle(escalated=0, exhausted=0)


async def test_an_acknowledged_incident_does_not_escalate() -> None:
    alerting = FakeAlerting()
    incident = Incident(alerting)
    incident.open = False  # someone acknowledged it
    cycle = await _escalator(incident, FakeClock(T0 + timedelta(hours=1))).run()
    assert (cycle, alerting.levels, incident.events) == (EscalationCycle(0, 0), [], [])
