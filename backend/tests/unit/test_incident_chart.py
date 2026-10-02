"""VIG-26: which readings an incident's chart shows, from where, and which line."""

from datetime import UTC, datetime, timedelta

from willay.incidents.domain.chart import (
    Point,
    Threshold,
    evidence,
    readings_window,
    series,
    threshold,
)

OPENED = datetime(2026, 10, 2, 3, 31, tzinfo=UTC)


def test_the_window_goes_from_an_hour_before_the_opening_to_two_after_or_now() -> None:
    long_after = OPENED + timedelta(days=3)
    assert readings_window(OPENED, long_after) == (
        OPENED - timedelta(hours=1),
        OPENED + timedelta(hours=2),
    )
    soon_after = OPENED + timedelta(minutes=20)
    assert readings_window(OPENED, soon_after) == (OPENED - timedelta(hours=1), soon_after)


def test_the_evidence_copy_is_read_in_order_and_an_odd_entry_is_skipped() -> None:
    payload = {
        "readings": [
            {"measured_at": "2026-10-02T03:31:03.480000+00:00", "value": 4.6},
            {"measured_at": "2026-10-02T03:30:53.480000+00:00", "value": 4.2},
            {"measured_at": "not a date", "value": 1},
            {"value": 9},
        ]
    }
    assert [p.value for p in evidence(payload)] == [4.2, 4.6]
    assert evidence({}) == []


def test_stored_readings_win_and_the_copy_only_fills_an_empty_window() -> None:
    stored = [Point(OPENED, 4.6)]
    copy = [Point(OPENED, 4.2)]
    assert series(stored, copy) == ("readings", stored)
    assert series([], copy) == ("evidence", copy)
    assert series([], []) == ("readings", [])


def test_only_a_threshold_rule_draws_its_boundary() -> None:
    opened = {"rule_type": "threshold", "rule_params": {"operator": "gt", "value": 3.5}}
    assert threshold(opened) == Threshold("gt", 3.5)
    assert threshold({"rule_type": "rate_of_change", "rule_params": {"delta": 40}}) is None
    assert threshold({"rule_type": "threshold", "rule_params": {}}) is None
