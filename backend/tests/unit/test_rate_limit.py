from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from willay.ingestion.application.rate_limit import enforce_rate_limit
from willay.ingestion.domain.rate_limit import (
    MAX_BATCHES_PER_MINUTE,
    RateLimitExceededError,
    check_count,
    seconds_until_next_window,
    window_start,
)
from willay.shared.clock import FakeClock

NOW = datetime(2026, 10, 12, 9, 15, 42, 300_000, tzinfo=UTC)


def test_window_is_the_start_of_the_minute() -> None:
    assert window_start(NOW) == datetime(2026, 10, 12, 9, 15, tzinfo=UTC)


@pytest.mark.parametrize(
    ("second", "expected"),
    [(0, 60), (42.3, 18), (59.9, 1)],
)
def test_retry_after_is_the_rest_of_the_minute_rounded_up(second: float, expected: int) -> None:
    now = window_start(NOW) + timedelta(seconds=second)
    assert seconds_until_next_window(now) == expected


def test_the_60th_batch_passes_and_the_61st_does_not() -> None:
    check_count(MAX_BATCHES_PER_MINUTE, NOW)
    with pytest.raises(RateLimitExceededError) as exc:
        check_count(MAX_BATCHES_PER_MINUTE + 1, NOW)
    assert exc.value.retry_after_s == 18


class FakeCounter:
    def __init__(self) -> None:
        self.counts: dict[tuple[UUID, datetime], int] = {}

    async def hit(self, station_id: UUID, window: datetime) -> int:
        key = (station_id, window)
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


async def test_limit_is_per_station_and_resets_with_the_next_minute() -> None:
    clock, counter = FakeClock(NOW), FakeCounter()
    busy, quiet = uuid4(), uuid4()

    for _ in range(MAX_BATCHES_PER_MINUTE):
        await enforce_rate_limit(busy, clock, counter)
    with pytest.raises(RateLimitExceededError):
        await enforce_rate_limit(busy, clock, counter)

    await enforce_rate_limit(quiet, clock, counter)  # other stations are unaffected
    clock.advance(timedelta(seconds=18))  # 09:16:00.3: a new window
    await enforce_rate_limit(busy, clock, counter)
