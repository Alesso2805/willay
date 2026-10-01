from collections.abc import Collection
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from vigia.shared.audit import AuditEntry
from vigia.shared.clock import FakeClock
from vigia.territory.application.stations import (
    Station,
    StationNotFoundError,
    create_station,
    deactivate_station,
    rotate_api_key,
    update_station,
)
from vigia.territory.application.zones import Actor
from vigia.territory.domain.stations import (
    InvalidStationError,
    Location,
    Source,
    StationData,
    StationStatus,
    Variable,
    ZoneAssignment,
    ZonePosition,
)

T0 = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
ACTOR = Actor(organization_id=uuid4(), user_id=uuid4())
ZONE = uuid4()
DATA = StationData(
    "Chaclacayo", Variable.DISCHARGE, Location(-76.76, -11.97), Source.SENSOR, 10, 3,
    StationStatus.ACTIVE, (ZoneAssignment(ZONE, ZonePosition.DOWNSTREAM),),
)  # fmt: skip


class FakeIssuer:
    def __init__(self) -> None:
        self.issued = 0

    def issue(self, station_id: UUID) -> tuple[str, str]:
        self.issued += 1
        key = f"{station_id}.secret-{self.issued}"
        return key, f"hash({key})"


class FakeStations:
    def __init__(self, zones: set[UUID]) -> None:
        self.zones = zones
        self.rows: dict[tuple[UUID, UUID], Station] = {}
        self.hashes: dict[UUID, str] = {}

    async def zones_of(self, organization_id: UUID, zone_ids: Collection[UUID]) -> set[UUID]:
        return set(zone_ids) & self.zones

    async def add(
        self,
        station_id: UUID,
        organization_id: UUID,
        code: str,
        data: StationData,
        api_key_hash: str,
        now: datetime,
    ) -> Station:
        station = Station(station_id, code, data, now, now)
        self.rows[(organization_id, station_id)] = station
        self.hashes[station_id] = api_key_hash
        return station

    async def get(
        self, organization_id: UUID, station_id: UUID, *, for_update: bool = False
    ) -> Station | None:
        return self.rows.get((organization_id, station_id))

    async def list(self, organization_id: UUID, *, include_inactive: bool) -> list[Station]:
        return [s for (org, _), s in self.rows.items() if org == organization_id]

    async def replace(self, organization_id: UUID, station_id: UUID, data: StationData) -> Station:
        station = replace(self.rows[(organization_id, station_id)], data=data)
        self.rows[(organization_id, station_id)] = station
        return station

    async def set_api_key_hash(
        self, organization_id: UUID, station_id: UUID, api_key_hash: str, now: datetime
    ) -> Station:
        self.hashes[station_id] = api_key_hash
        station = replace(self.rows[(organization_id, station_id)], api_key_rotated_at=now)
        self.rows[(organization_id, station_id)] = station
        return station


class FakeAudit:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


@pytest.fixture
def stations() -> FakeStations:
    return FakeStations(zones={ZONE})


async def _create(
    stations: FakeStations, audit: FakeAudit, issuer: FakeIssuer
) -> tuple[Station, str]:
    issued = await create_station(
        ACTOR, "RIM-CHA-09", DATA,
        stations=stations, issuer=issuer, audit=audit, clock=FakeClock(T0),
    )  # fmt: skip
    return issued.station, issued.api_key


async def test_create_returns_the_key_once_and_stores_only_its_hash(stations: FakeStations) -> None:
    audit = FakeAudit()
    station, api_key = await _create(stations, audit, FakeIssuer())

    assert api_key.startswith(f"{station.id}.")
    assert stations.hashes[station.id] == f"hash({api_key})"
    [entry] = audit.entries
    assert entry.after is not None
    assert "api_key" not in str(entry.after)
    assert entry.after["unit"] == "m3/s"


async def test_zones_of_other_organizations_are_unknown(stations: FakeStations) -> None:
    foreign = replace(DATA, zones=(ZoneAssignment(uuid4(), ZonePosition.IN_ZONE),))
    with pytest.raises(InvalidStationError, match="desconocidas"):
        await create_station(
            ACTOR, "X-01", foreign,
            stations=stations, issuer=FakeIssuer(), audit=FakeAudit(), clock=FakeClock(T0),
        )  # fmt: skip
    assert stations.rows == {}


async def test_rotation_replaces_the_hash_and_audits_only_the_date(stations: FakeStations) -> None:
    audit, issuer = FakeAudit(), FakeIssuer()
    station, old_key = await _create(stations, audit, issuer)
    clock = FakeClock(T0 + timedelta(days=30))

    rotated = await rotate_api_key(
        ACTOR, station.id, stations=stations, issuer=issuer, audit=audit, clock=clock
    )

    assert rotated.api_key != old_key
    assert stations.hashes[station.id] == f"hash({rotated.api_key})"  # the old one is gone
    assert rotated.station.api_key_rotated_at == T0 + timedelta(days=30)
    entry = audit.entries[-1]
    assert entry.action == "rotate_api_key"
    assert rotated.api_key not in f"{entry.before}{entry.after}"


async def test_update_without_changes_writes_nothing(stations: FakeStations) -> None:
    audit = FakeAudit()
    station, _ = await _create(stations, audit, FakeIssuer())
    await update_station(
        ACTOR, station.id, DATA, stations=stations, audit=audit, clock=FakeClock(T0)
    )
    assert [e.action for e in audit.entries] == ["create"]


async def test_deactivate_is_idempotent_and_foreign_actors_get_not_found(
    stations: FakeStations,
) -> None:
    audit = FakeAudit()
    station, _ = await _create(stations, audit, FakeIssuer())
    clock = FakeClock(T0)

    await deactivate_station(ACTOR, station.id, stations=stations, audit=audit, clock=clock)
    await deactivate_station(ACTOR, station.id, stations=stations, audit=audit, clock=clock)
    assert [e.action for e in audit.entries] == ["create", "deactivate"]

    intruder = Actor(organization_id=uuid4(), user_id=uuid4())
    with pytest.raises(StationNotFoundError):
        await rotate_api_key(
            intruder, station.id, stations=stations, issuer=FakeIssuer(), audit=audit, clock=clock
        )
