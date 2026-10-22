"""VIG-30: what `make demo` narrates and its verdict on SPEC's Rímac story."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from willay.demo.story import (
    DROP_RULE,
    OPEN_GRACE_S,
    SILENCE_RULE,
    Case,
    IncidentState,
    Outcome,
    StoryEvent,
    clock_text,
    hint,
    judge,
    narrate,
    scenario_notes,
    status_line,
    summary,
)
from willay.incidents.domain.lifecycle import IncidentStatus
from willay.ingestion.domain.simulation import Behavior, StationPlan

T0 = datetime(2026, 10, 3, 13, 40, tzinfo=UTC)


def _incident(
    *,
    status: IncidentStatus = IncidentStatus.OPEN,
    level: int = 1,
    acknowledged: bool = False,
    exhausted: bool = False,
) -> IncidentState:
    return IncidentState(uuid4(), DROP_RULE, status, level, acknowledged, exhausted)


def _acknowledged(level: int) -> IncidentState:
    return _incident(status=IncidentStatus.ACKNOWLEDGED, level=level, acknowledged=True)


def test_the_story_passes_when_level_2_acknowledges_both_incidents() -> None:
    cases = [Case("drop", _acknowledged(2), 400.0), Case("silence", _acknowledged(2), 150.0)]
    assert judge(cases).outcome is Outcome.PASSED


def test_it_waits_while_an_incident_is_still_climbing_the_levels() -> None:
    cases = [Case("drop", _acknowledged(2), 400.0), Case("silence", _incident(level=2), 150.0)]
    assert judge(cases).outcome is Outcome.WAITING
    # Before the river silences Santa Eulalia there is nothing to expect yet.
    assert judge([Case("drop", _incident(), 30.0), Case("silence", None, None)]).outcome is (
        Outcome.WAITING
    )


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        (
            Case("drop", _acknowledged(1), 60.0),
            "the drop incident was acknowledged at level 1; the story needs level 2 to"
            " acknowledge it",
        ),
        (
            Case("silence", _incident(level=3), 400.0),
            "nobody at level 2 acknowledged the silence incident: it escalated to level 3",
        ),
        (
            Case("drop", _incident(status=IncidentStatus.RESOLVED), 60.0),
            "the drop incident was resolved without being acknowledged",
        ),
        (
            Case("drop", _incident(level=2, exhausted=True), 400.0),
            "the drop incident exhausted its escalation without an acknowledgement",
        ),
        (
            Case("silence", None, OPEN_GRACE_S + 1),
            "the silence opened no incident within 90 s: are the workers running?",
        ),
    ],
)
def test_each_way_the_story_goes_wrong_is_named(case: Case, reason: str) -> None:
    verdict = judge([case])
    assert verdict.outcome is Outcome.FAILED
    assert verdict.reason == reason


def test_an_incident_may_take_its_time_to_open_within_the_grace() -> None:
    assert judge([Case("silence", None, OPEN_GRACE_S)]).outcome is Outcome.WAITING


def _event(event_type: str, payload: dict[str, Any] | None = None, **fields: Any) -> StoryEvent:
    values: dict[str, Any] = {
        "id": 1,
        "incident_id": uuid4(),
        "rule_id": DROP_RULE,
        "occurred_at": T0,
        "event_type": event_type,
        "actor_type": "system",
        "payload": payload or {},
        "actor_name": None,
        "contact_name": None,
        "station_code": "RIM-CHA-01",
    }
    return StoryEvent(**(values | fields))


@pytest.mark.parametrize(
    ("event", "text"),
    [
        (
            _event("opened", {"rule_type": "rate_of_change", "trigger_value": 33.9,
                              "rule_params": {"direction": "down"}}),
            "incident opened at RIM-CHA-01: sudden drop, value 33.9",
        ),
        (
            _event("opened", {"rule_type": "threshold", "trigger_value": 3.7}),
            "incident opened at RIM-CHA-01: value out of bounds, 3.7",
        ),
        (
            _event("opened", {"rule_type": "silence", "trigger_value": 85.2}),
            "incident opened at RIM-CHA-01: the station stopped reporting, last value 85.2",
        ),
        (
            _event("alert_sent", {"channel": "email", "level_order": 1}, contact_name="Óscar"),
            "level 1: email sent to Óscar",
        ),
        (
            _event("alert_failed", {"channel": "telegram", "level_order": 2, "final": False},
                   contact_name="Rosa"),
            "level 2: Telegram to Rosa failed; it will be retried",
        ),
        (
            _event("alert_skipped",
                   {"channel": "telegram", "level_order": 2, "reason_code": "no_telegram"},
                   contact_name="Lucho"),
            "level 2: Lucho skipped on Telegram (no telegram)",
        ),
        (
            _event("escalated", {"from_level": 1, "to_level": 2}),
            "nobody acknowledged: escalated to level 2",
        ),
        (
            _event("acknowledged", actor_type="contact", actor_name="Rosa Brigada",
                   acknowledged_channel="telegram"),
            "acknowledged by Rosa Brigada from their Telegram alert",
        ),
        (
            _event("acknowledged", actor_type="user", actor_name="Ana"),
            "acknowledged by Ana",
        ),
        (
            _event("resolved", {"resolution": "false_alarm"}, actor_name="Ana"),
            "marked as a false alarm by Ana",
        ),
        (_event("station_recovered"), "RIM-CHA-01 reports again"),
    ],
)  # fmt: skip
def test_events_are_told_in_the_terms_of_the_dashboard(event: StoryEvent, text: str) -> None:
    assert narrate(event) == text


def test_hints_point_to_the_dashboard_and_to_level_2() -> None:
    opened = _event("opened", {"rule_type": "silence"})
    assert hint(opened, "http://localhost:4200") == (
        f"see it in the dashboard: http://localhost:4200/incidentes/{opened.incident_id}"
    )
    assert "level 2 can acknowledge now" in (hint(_event("escalated", {"to_level": 2}), "") or "")
    assert hint(_event("escalated", {"to_level": 3}), "") is None
    assert hint(_event("alert_sent", {"level_order": 1}), "") is None


def test_the_river_is_told_only_when_it_does_something() -> None:
    plans = [
        StationPlan("RIM-CHA-01", "discharge", Behavior.DROP, 6),
        StationPlan("RIM-SEU-01", "discharge", Behavior.SILENCE, 30),
        StationPlan("RIM-CHO-01", "water_level", Behavior.NORMAL),
    ]
    values = {"RIM-CHA-01": 34.0, "RIM-SEU-01": 84.0, "RIM-CHO-01": 2.0}
    previous = {"RIM-CHA-01": 85.3, "RIM-SEU-01": 85.0, "RIM-CHO-01": 2.0}
    assert scenario_notes(plans, 6, values, previous) == [
        "RIM-CHA-01 (Chaclacayo (aguas abajo)): discharge falls from 85.3 to 34 m3/s"
    ]
    assert scenario_notes(plans, 30, values | {"RIM-SEU-01": None}, previous) == [
        "RIM-SEU-01 (Santa Eulalia (aguas arriba)) stops reporting"
    ]
    assert scenario_notes(plans, 7, values, previous) == []


def test_the_status_line_says_where_each_incident_stands() -> None:
    cases = [Case("drop", _incident(level=2), 130.0), Case("silence", None, None)]
    assert status_line(125, cases) == "2:05 elapsed · drop: open at level 2 · silence: not yet"


def test_the_summary_says_who_acknowledged_each_incident_and_when() -> None:
    drop, silence = uuid4(), uuid4()
    events = [
        _event("opened", incident_id=drop),
        _event("opened", incident_id=silence, rule_id=SILENCE_RULE, station_code="RIM-SEU-01",
               occurred_at=T0 + timedelta(minutes=4)),
        _event("acknowledged", incident_id=drop, actor_name="Rosa Brigada",
               occurred_at=T0 + timedelta(seconds=170)),
        _event("acknowledged", incident_id=silence, rule_id=SILENCE_RULE,
               actor_name="Rosa Brigada", occurred_at=T0 + timedelta(minutes=7)),
    ]  # fmt: skip
    assert summary(events) == [
        "drop: opened at RIM-CHA-01, acknowledged by Rosa Brigada 2:50 later",
        "silence: opened at RIM-SEU-01, acknowledged by Rosa Brigada 3:00 later",
    ]


def test_clock_text() -> None:
    assert [clock_text(s) for s in (0, 59.9, 75, 600)] == ["0:00", "0:59", "1:15", "10:00"]
