from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from vigia.ingestion.application.authenticate_station import (
    AuthenticatedStation,
    InactiveStationError,
    InvalidApiKeyError,
    StationCredential,
    authenticate_station,
)
from vigia.ingestion.application.ingest_batch import ingest_batch
from vigia.ingestion.domain.api_keys import generate_api_key
from vigia.ingestion.domain.readings import (
    MAX_CLOCK_SKEW,
    FutureReadingsError,
    Reading,
    check_not_in_future,
    in_measurement_order,
)
from vigia.shared.clock import FakeClock

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
STATION = uuid4()
ORG = uuid4()


# --- dominio -----------------------------------------------------------------------


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


def test_batch_is_processed_in_measurement_order() -> None:
    late, early = Reading(NOW, 2.0), Reading(NOW - timedelta(seconds=10), 1.0)
    assert in_measurement_order([late, early]) == [early, late]


# --- autenticación de estación -----------------------------------------------------


class FakeVerifier:
    dummy_hash = "dummy"

    def __init__(self) -> None:
        self.verified_against: list[str] = []

    def verify(self, api_key_hash: str, api_key: str) -> bool:
        self.verified_against.append(api_key_hash)
        return api_key_hash == f"hash:{api_key}"


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


@pytest.mark.parametrize("raw", [None, "", "sin-formato", "no-uuid.secreto"])
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
    # Sin esto, responder más rápido a ids inexistentes revelaría qué estaciones existen.
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


# --- ingesta -----------------------------------------------------------------------


class FakeWriter:
    def __init__(self, existing: int = 0) -> None:
        self.existing = existing
        self.calls: list[tuple[list[Reading], datetime]] = []

    async def store_and_enqueue(
        self,
        station_id: UUID,
        organization_id: UUID,
        readings: Sequence[Reading],
        received_at: datetime,
    ) -> tuple[int, int]:
        self.calls.append((list(readings), received_at))
        stored = len(readings) - self.existing
        return stored, stored


async def test_batch_is_stored_sorted_with_received_at_from_the_clock() -> None:
    writer = FakeWriter(existing=1)
    readings = [Reading(NOW, 2.0), Reading(NOW - timedelta(seconds=10), 1.0)]

    result = await ingest_batch(
        AuthenticatedStation(STATION, ORG), readings, FakeClock(NOW), writer
    )

    assert writer.calls == [(sorted(readings, key=lambda r: r.measured_at), NOW)]
    assert (result.received, result.stored, result.duplicates) == (2, 1, 1)


async def test_future_readings_reject_the_whole_batch() -> None:
    writer = FakeWriter()
    with pytest.raises(FutureReadingsError):
        await ingest_batch(
            AuthenticatedStation(STATION, ORG),
            [Reading(NOW, 1.0), Reading(NOW + timedelta(hours=1), 2.0)],
            FakeClock(NOW),
            writer,
        )
    assert writer.calls == []  # nada se guarda: el lote es todo o nada
