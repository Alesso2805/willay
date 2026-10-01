from datetime import UTC, datetime, timedelta, timezone

import pytest
import time_machine

from vigia.shared.clock import Clock, FakeClock, SystemClock

START = datetime(2026, 10, 1, 8, 40, tzinfo=UTC)


def test_system_clock_returns_utc_and_follows_time_machine() -> None:
    with time_machine.travel(START, tick=False):
        now = SystemClock().now()
    assert now == START
    assert now.tzinfo == UTC


def test_fake_clock_only_moves_when_advanced() -> None:
    clock = FakeClock(START)
    assert clock.now() == START
    clock.advance(timedelta(seconds=45))
    assert clock.now() == START + timedelta(seconds=45)


def test_fake_clock_normalizes_to_utc() -> None:
    lima = timezone(timedelta(hours=-5))
    clock = FakeClock(datetime(2026, 10, 1, 3, 40, tzinfo=lima))
    assert clock.now() == START
    assert clock.now().tzinfo == UTC


def test_fake_clock_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FakeClock(datetime(2026, 10, 1))  # noqa: DTZ001 - exactly what is under test
    clock = FakeClock(START)
    with pytest.raises(ValueError, match="timezone-aware"):
        clock.set(datetime(2026, 10, 1))  # noqa: DTZ001


def test_fake_clock_does_not_go_backwards() -> None:
    with pytest.raises(ValueError, match="does not go back"):
        FakeClock(START).advance(timedelta(seconds=-1))


def test_both_implementations_satisfy_protocol() -> None:
    clocks: list[Clock] = [SystemClock(), FakeClock(START)]
    assert all(c.now().tzinfo == UTC for c in clocks)
