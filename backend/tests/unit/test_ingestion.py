from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from willay.ingestion.application.authenticate_station import (
    AuthenticatedStation,
    InactiveStationError,
    InvalidApiKeyError,
    StationCredential,
    authenticate_station,
)
from willay.ingestion.application.ingest_batch import StoreCounts, ingest_batch
from willay.ingestion.domain.api_keys import generate_api_key
from willay.ingestion.domain.readings import (
    LATE_AFTER,
    MAX_CLOCK_SKEW,
    ClassifiedReading,
    FutureReadingsError,
    Quality,
    Reading,
    check_not_in_future,
    classify,
    heartbeat_reading,
    quality_of,
)
from willay.shared.clock import FakeClock

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
STATION = uuid4()
ORG = uuid4()


def test_readings_up_to_the_clock_skew_are_accepted() -> None:
    check_not_in_future(
        [Reading(NOW + MAX_CLOCK_SKEW, 1.0), Reading(NOW - timedelta(days=2), 1)], NOW
    )


def test_readings_beyond_the_clock_skew_are_reported_by_index() -> None:
    readings = [
        Reading(NOW, 1.0),
        Reading(NOW + MAX_CLOCK_SKEW + timedelta(seconds=1), 2.0),
        Reading(NOW + timedelta(hours=1), 3.0),
    ]
    with pytest.raises(FutureReadingsError) as exc:
        check_not_in_future(readings, NOW)
    assert exc.value.indices == [1, 2]


def test_a_reading_is_late_only_after_more_than_one_hour() -> None:
    assert quality_of(NOW - LATE_AFTER, NOW) is Quality.OK  # exactly 1 h: still on time
    assert quality_of(NOW - LATE_AFTER - timedelta(microseconds=1), NOW) is Quality.LATE


def test_classify_sorts_by_measurement_and_marks_quality() -> None:
    old = Reading(NOW - timedelta(hours=3), 1.0)
    recent = Reading(NOW - timedelta(seconds=10), 2.0)
    assert classify([recent, old], NOW) == [
        ClassifiedReading(old.measured_at, 1.0, Quality.LATE),
        ClassifiedReading(recent.measured_at, 2.0, Quality.OK),
    ]


def test_heartbeat_comes_from_the_latest_on_time_reading() -> None:
    readings = [
        ClassifiedReading(NOW - timedelta(hours=3), 9.0, Quality.LATE),
        ClassifiedReading(NOW - timedelta(seconds=20), 1.0, Quality.OK),
        ClassifiedReading(NOW - timedelta(seconds=10), 2.0, Quality.OK),
    ]
    assert heartbeat_reading(readings) == readings[2]


def test_a_batch_of_only_late_readings_does_not_beat() -> None:
    assert (
        heartbeat_reading([ClassifiedReading(NOW - timedelta(hours=3), 9.0, Quality.LATE)]) is None
    )


class FakeVerifier:
    dummy_hash = "dummy"

    def __init__(self) -> None:
        self.verified_against: list[str] = []

    def verify(self, api_key_hash: str, api_key: str) -> bool:
        self.verified_against.append(api_key_hash)
        return api_key_hash == f"hash:{api_key}"

    def remembers(self, api_key_hash: str, api_key: str) -> bool:
        return False


class FakeCredentials:
    def __init__(self, *credentials: StationCredential) -> None:
        self._by_id = {c.station_id: c for c in credentials}

    async def find(self, station_id: UUID) -> StationCredential | None:
        return self._by_id.get(station_id)


def _credential(key: str, *, active: bool = True) -> StationCredential:
    return StationCredential(STATION, ORG, f"hash:{key}", active)


async def test_valid_key_identifies_station_and_its_organization() -> None:
    key = generate_api_key(STATION)
    station = await authenticate_station(key, FakeCredentials(_credential(key)), FakeVerifier())
    assert station == AuthenticatedStation(STATION, ORG)


@pytest.mark.parametrize("raw", [None, "", "no-format", "not-a-uuid.secret"])
async def test_missing_or_malformed_key_is_rejected(raw: str | None) -> None:
    with pytest.raises(InvalidApiKeyError):
        await authenticate_station(raw, FakeCredentials(), FakeVerifier())


async def test_wrong_secret_is_rejected() -> None:
    stored = generate_api_key(STATION)
    with pytest.raises(InvalidApiKeyError):
        await authenticate_station(
            generate_api_key(STATION), FakeCredentials(_credential(stored)), FakeVerifier()
        )


async def test_unknown_station_still_pays_a_hash_verification() -> None:
    # Otherwise, answering unknown ids faster would reveal which stations exist.
    verifier = FakeVerifier()
    with pytest.raises(InvalidApiKeyError):
        await authenticate_station(generate_api_key(uuid4()), FakeCredentials(), verifier)
    assert verifier.verified_against == ["dummy"]


async def test_inactive_station_is_forbidden_even_with_the_right_key() -> None:
    key = generate_api_key(STATION)
    with pytest.raises(InactiveStationError):
        await authenticate_station(
            key, FakeCredentials(_credential(key, active=False)), FakeVerifier()
        )


class FakeWriter:
    def __init__(self, existing: int = 0) -> None:
        self.existing = existing
        self.calls: list[tuple[list[ClassifiedReading], datetime]] = []
        self.heartbeats: list[ClassifiedReading | None] = []
        self.correlation_ids: list[UUID] = []

    async def store_and_enqueue(
        self,
        station_id: UUID,
        organization_id: UUID,
        readings: Sequence[ClassifiedReading],
        received_at: datetime,
        heartbeat: ClassifiedReading | None,
        correlation_id: UUID,
    ) -> StoreCounts:
        self.calls.append((list(readings), received_at))
        self.correlation_ids.append(correlation_id)
        self.heartbeats.append(heartbeat)
        new = readings[self.existing :]
        late = sum(1 for r in new if r.quality is Quality.LATE)
        return StoreCounts(stored=len(new), late=late, enqueued=len(new) - late)


async def test_batch_is_classified_sorted_and_stamped_with_the_clock() -> None:
    writer = FakeWriter(existing=1)
    readings = [Reading(NOW, 2.0), Reading(NOW - timedelta(hours=2), 1.0)]

    result = await ingest_batch(
        AuthenticatedStation(STATION, ORG), readings, FakeClock(NOW), writer
    )

    assert writer.calls == [
        (
            [
                ClassifiedReading(NOW - timedelta(hours=2), 1.0, Quality.LATE),
                ClassifiedReading(NOW, 2.0, Quality.OK),
            ],
            NOW,
        )
    ]
    assert (result.received, result.counts.stored, result.duplicates) == (2, 1, 1)
    assert writer.heartbeats == [ClassifiedReading(NOW, 2.0, Quality.OK)]


async def test_each_batch_gets_its_own_correlation_id_for_the_logs() -> None:
    writer = FakeWriter()
    station = AuthenticatedStation(STATION, ORG)
    first = await ingest_batch(station, [Reading(NOW, 1.0)], FakeClock(NOW), writer)
    second = await ingest_batch(station, [Reading(NOW, 2.0)], FakeClock(NOW), writer)
    # The queue rows get the same id the API returns and logs.
    assert writer.correlation_ids == [first.correlation_id, second.correlation_id]
    assert first.correlation_id != second.correlation_id


async def test_future_readings_reject_the_whole_batch() -> None:
    writer = FakeWriter()
    with pytest.raises(FutureReadingsError):
        await ingest_batch(
            AuthenticatedStation(STATION, ORG),
            [Reading(NOW, 1.0), Reading(NOW + timedelta(hours=1), 2.0)],
            FakeClock(NOW),
            writer,
        )
    assert writer.calls == []  # nothing is stored: the batch is all or nothing
