"""Injectable clock.

The domain and workers receive a `Clock` instead of calling `datetime.now()`, so tests advance
time with `FakeClock` without real waits. Ruff (TID251) bans `datetime.now()` outside this file.
"""

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current instant, always timezone-aware UTC."""
        ...


class SystemClock:
    """Real implementation: the only one that reads the system clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    """Controlled clock for tests: only advances when told to."""

    def __init__(self, start: datetime) -> None:
        self._now = _require_aware(start)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        if delta < timedelta(0):
            raise ValueError("FakeClock does not go back; use set() if you need to")
        self._now += delta

    def set(self, instant: datetime) -> None:
        self._now = _require_aware(instant)


def _require_aware(instant: datetime) -> datetime:
    # A naive datetime would compare wrongly against Postgres timestamptz values.
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("The clock only accepts timezone-aware datetimes")
    return instant.astimezone(UTC)
