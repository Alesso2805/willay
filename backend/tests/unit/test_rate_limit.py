from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from willay.ingestion.application.authenticate_station import (
    InactiveStationError,
    InvalidApiKeyError,
    StationCredential,
    authenticate_station,
)
from willay.ingestion.application.rate_limit import KeyFailureLimit, enforce_rate_limit
from willay.ingestion.domain.rate_limit import (
    MAX_BATCHES_PER_MINUTE,
    MAX_KEY_FAILURES_PER_MINUTE,
    KeyFailuresExceededError,
    RateLimitExceededError,
    check_count,
    check_key_failures,
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


def test_the_30th_wrong_key_is_checked_and_the_31st_is_not() -> None:
    check_key_failures(MAX_KEY_FAILURES_PER_MINUTE, NOW)
    with pytest.raises(KeyFailuresExceededError) as exc:
        check_key_failures(MAX_KEY_FAILURES_PER_MINUTE + 1, NOW)
    assert exc.value.retry_after_s == 18


STATION = UUID("01a0dc43-cd2d-7522-8430-867cee8f89ce")
RIGHT_KEY = f"{STATION}.right"
WRONG_KEY = f"{STATION}.wrong"
GUESSER, NEIGHBOUR = "203.0.113.7", "198.51.100.4"


class FakeKeyFailures:
    def __init__(self) -> None:
        self.counts: dict[tuple[str, datetime], int] = {}
        self.hits = 0

    async def hit(self, client: str, window: datetime) -> int:
        self.hits += 1
        key = (client, window)
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def refund(self, client: str, window: datetime) -> None:
        self.counts[(client, window)] -= 1


class OneStation:
    def __init__(self, *, active: bool = True) -> None:
        self.active = active

    async def find(self, station_id: UUID) -> StationCredential | None:
        if station_id != STATION:
            return None
        return StationCredential(STATION, uuid4(), "its hash", self.active)


class RememberingVerifier:
    """Like ApiKeyHasher: a right key, once checked, is answered from memory."""

    dummy_hash = "a hash nobody has"

    def __init__(self) -> None:
        self.checks = 0
        self.remembered: set[str] = set()

    def verify(self, api_key_hash: str, api_key: str) -> bool:
        if api_key in self.remembered:
            return True
        self.checks += 1
        if api_key != RIGHT_KEY:
            return False
        self.remembered.add(api_key)
        return True

    def remembers(self, api_key_hash: str, api_key: str) -> bool:
        return api_key in self.remembered


async def test_wrong_keys_are_cut_off_before_their_check_and_only_for_that_address() -> None:
    clock, failures, verifier = FakeClock(NOW), FakeKeyFailures(), RememberingVerifier()

    async def attempt(key: str, client: str = GUESSER) -> None:
        limit = KeyFailureLimit(client, clock, failures)
        await authenticate_station(key, OneStation(), verifier, limit)

    for _ in range(MAX_KEY_FAILURES_PER_MINUTE):
        with pytest.raises(InvalidApiKeyError):
            await attempt(WRONG_KEY)
    with pytest.raises(KeyFailuresExceededError):
        await attempt(WRONG_KEY)
    with pytest.raises(KeyFailuresExceededError):
        await attempt(RIGHT_KEY)  # a key not checked yet waits too, from that address
    assert verifier.checks == MAX_KEY_FAILURES_PER_MINUTE

    await attempt(RIGHT_KEY, client=NEIGHBOUR)  # other addresses are unaffected
    await attempt(RIGHT_KEY)  # once remembered, a right key needs no check, from anywhere
    clock.advance(timedelta(seconds=18))  # 09:16:00.3: a new window
    with pytest.raises(InvalidApiKeyError):
        await attempt(WRONG_KEY)


async def test_a_right_key_takes_its_count_back_and_is_not_counted_once_remembered() -> None:
    clock, failures, verifier = FakeClock(NOW), FakeKeyFailures(), RememberingVerifier()

    for _ in range(MAX_KEY_FAILURES_PER_MINUTE + 5):
        limit = KeyFailureLimit(NEIGHBOUR, clock, failures)
        await authenticate_station(RIGHT_KEY, OneStation(), verifier, limit)

    assert failures.hits == 1  # only the first one ran Argon2id
    assert failures.counts == {(NEIGHBOUR, window_start(NOW)): 0}


async def test_an_inactive_station_s_right_key_takes_its_count_back() -> None:
    clock, failures = FakeClock(NOW), FakeKeyFailures()
    limit = KeyFailureLimit(NEIGHBOUR, clock, failures)
    with pytest.raises(InactiveStationError):
        await authenticate_station(
            RIGHT_KEY, OneStation(active=False), RememberingVerifier(), limit
        )
    assert failures.counts == {(NEIGHBOUR, window_start(NOW)): 0}
