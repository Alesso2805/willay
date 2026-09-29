from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from vigia.shared.audit import AuditEntry
from vigia.shared.clock import FakeClock
from vigia.territory.application.zones import (
    Actor,
    Zone,
    ZoneNotFoundError,
    create_zone,
    deactivate_zone,
    update_zone,
)
from vigia.territory.domain.zones import (
    InvalidGeometryError,
    MultiPolygonCoords,
    RiskLevel,
    ZoneData,
)

T0 = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
SQUARE: MultiPolygonCoords = [
    [[(-76.7, -11.9), (-76.6, -11.9), (-76.6, -12.0), (-76.7, -12.0), (-76.7, -11.9)]]
]
DATA = ZoneData("Chosica", None, RiskLevel.HIGH, 1000, SQUARE)
ACTOR = Actor(organization_id=uuid4(), user_id=uuid4())


class FakeZones:
    def __init__(self, invalid: str | None = None) -> None:
        self.invalid = invalid
        self.rows: dict[tuple[UUID, UUID], Zone] = {}

    async def invalid_reason(self, geometry: MultiPolygonCoords) -> str | None:
        return self.invalid

    async def add(
        self, zone_id: UUID, organization_id: UUID, data: ZoneData, now: datetime
    ) -> Zone:
        zone = Zone(zone_id, data, now, now)
        self.rows[(organization_id, zone_id)] = zone
        return zone

    async def get(
        self, organization_id: UUID, zone_id: UUID, *, for_update: bool = False
    ) -> Zone | None:
        return self.rows.get((organization_id, zone_id))

    async def list(self, organization_id: UUID, *, include_inactive: bool) -> list[Zone]:
        return [z for (org, _), z in self.rows.items() if org == organization_id]

    async def replace(
        self, organization_id: UUID, zone_id: UUID, data: ZoneData, now: datetime
    ) -> Zone:
        old = self.rows[(organization_id, zone_id)]
        zone = Zone(zone_id, data, old.created_at, now)
        self.rows[(organization_id, zone_id)] = zone
        return zone


class FakeAudit:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


async def _created(zones: FakeZones, audit: FakeAudit, clock: FakeClock) -> Zone:
    return await create_zone(ACTOR, DATA, zones=zones, audit=audit, clock=clock)


async def test_create_stores_the_zone_and_audits_it() -> None:
    zones, audit, clock = FakeZones(), FakeAudit(), FakeClock(T0)
    zone = await _created(zones, audit, clock)

    assert zones.rows[(ACTOR.organization_id, zone.id)].data == DATA
    [entry] = audit.entries
    assert (entry.action, entry.actor_id, entry.entity_id, entry.at) == (
        "create",
        ACTOR.user_id,
        zone.id,
        T0,
    )
    assert entry.before is None
    assert entry.after is not None
    assert entry.after["geometry"]["type"] == "MultiPolygon"


async def test_topologically_invalid_geometry_is_rejected_and_nothing_is_written() -> None:
    zones, audit = FakeZones(invalid="Self-intersection[-76.65 -11.95]"), FakeAudit()
    with pytest.raises(InvalidGeometryError, match="Self-intersection"):
        await _created(zones, audit, FakeClock(T0))
    assert zones.rows == {}
    assert audit.entries == []


async def test_update_audits_before_and_after() -> None:
    zones, audit, clock = FakeZones(), FakeAudit(), FakeClock(T0)
    zone = await _created(zones, audit, clock)
    clock.advance(timedelta(minutes=5))

    updated = await update_zone(
        ACTOR, zone.id, replace(DATA, risk_level=RiskLevel.CRITICAL),
        zones=zones, audit=audit, clock=clock,
    )  # fmt: skip

    assert updated.updated_at == T0 + timedelta(minutes=5)
    entry = audit.entries[-1]
    assert entry.action == "update"
    assert entry.before is not None
    assert entry.after is not None
    assert (entry.before["risk_level"], entry.after["risk_level"]) == ("high", "critical")


async def test_update_without_changes_writes_nothing() -> None:
    zones, audit, clock = FakeZones(), FakeAudit(), FakeClock(T0)
    zone = await _created(zones, audit, clock)
    await update_zone(ACTOR, zone.id, DATA, zones=zones, audit=audit, clock=clock)
    assert [e.action for e in audit.entries] == ["create"]


async def test_zone_of_another_organization_is_not_found() -> None:
    zones, audit, clock = FakeZones(), FakeAudit(), FakeClock(T0)
    zone = await _created(zones, audit, clock)
    intruder = Actor(organization_id=uuid4(), user_id=uuid4())

    with pytest.raises(ZoneNotFoundError):
        await update_zone(intruder, zone.id, DATA, zones=zones, audit=audit, clock=clock)
    with pytest.raises(ZoneNotFoundError):
        await deactivate_zone(intruder, zone.id, zones=zones, audit=audit, clock=clock)


async def test_deactivate_is_audited_once_and_idempotent() -> None:
    zones, audit, clock = FakeZones(), FakeAudit(), FakeClock(T0)
    zone = await _created(zones, audit, clock)

    await deactivate_zone(ACTOR, zone.id, zones=zones, audit=audit, clock=clock)
    await deactivate_zone(ACTOR, zone.id, zones=zones, audit=audit, clock=clock)

    assert zones.rows[(ACTOR.organization_id, zone.id)].data.is_active is False
    assert [e.action for e in audit.entries] == ["create", "deactivate"]
