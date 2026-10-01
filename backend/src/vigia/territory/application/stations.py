"""Station use cases. Everything filters by the actor's organization.

The plaintext API key exists only in the create/rotate response: its hash is stored, and it
never enters the audit log or the logs.
"""

import asyncio
from collections.abc import Collection
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from uuid_utils.compat import uuid7

from vigia.shared.audit import AuditEntry, AuditLog
from vigia.shared.clock import Clock
from vigia.territory.application.zones import Actor
from vigia.territory.domain.stations import (
    InvalidStationError,
    StationData,
    StationStatus,
    check_zones,
)

ENTITY_TYPE = "station"


@dataclass(frozen=True)
class Heartbeat:
    last_seen_at: datetime
    last_measured_at: datetime
    last_value: float | None


@dataclass(frozen=True)
class Station:
    id: UUID
    code: str
    data: StationData
    api_key_rotated_at: datetime
    created_at: datetime
    heartbeat: Heartbeat | None = None  # read-only: comes from ingest.station_heartbeats

    def snapshot(self) -> dict[str, Any]:
        """Audited state. No api_key_hash: not even the key hash goes to the audit log."""
        return {
            "code": self.code,
            "name": self.data.name,
            "variable": self.data.variable.value,
            "unit": self.data.unit,
            "location": [self.data.location.lon, self.data.location.lat],
            "source": self.data.source.value,
            "expected_interval_s": self.data.expected_interval_s,
            "silence_multiplier": self.data.silence_multiplier,
            "status": self.data.status.value,
            "zones": [
                {"zone_id": str(z.zone_id), "position": z.position.value} for z in self.data.zones
            ],
        }


class ApiKeyIssuer(Protocol):
    def issue(self, station_id: UUID) -> tuple[str, str]:
        """Generate a key for the station. Returns (plaintext key, hash)."""
        ...


class StationRepository(Protocol):
    async def zones_of(self, organization_id: UUID, zone_ids: Collection[UUID]) -> set[UUID]:
        """Of those zones, the ones belonging to the organization."""
        ...

    async def add(
        self,
        station_id: UUID,
        organization_id: UUID,
        code: str,
        data: StationData,
        api_key_hash: str,
        now: datetime,
    ) -> Station:
        """Raises DuplicateStationCodeError if the code already exists in the organization."""
        ...

    async def get(
        self, organization_id: UUID, station_id: UUID, *, for_update: bool = False
    ) -> Station | None: ...

    async def list(self, organization_id: UUID, *, include_inactive: bool) -> list[Station]: ...

    async def replace(
        self, organization_id: UUID, station_id: UUID, data: StationData
    ) -> Station: ...

    async def set_api_key_hash(
        self, organization_id: UUID, station_id: UUID, api_key_hash: str, now: datetime
    ) -> Station: ...


class StationNotFoundError(Exception):
    """Not found in the actor's organization (404, even if it exists in another one)."""


class DuplicateStationCodeError(Exception):
    """Another station of the organization already uses the code (409)."""


@dataclass(frozen=True)
class IssuedStation:
    station: Station
    api_key: str  # plaintext: show only once


async def create_station(
    actor: Actor,
    code: str,
    data: StationData,
    *,
    stations: StationRepository,
    issuer: ApiKeyIssuer,
    audit: AuditLog,
    clock: Clock,
) -> IssuedStation:
    await _check_zones(actor, data, stations)
    now = clock.now()
    station_id = uuid7()
    # Argon2id takes tens of ms: run it in a thread to keep the event loop free.
    api_key, api_key_hash = await asyncio.to_thread(issuer.issue, station_id)
    station = await stations.add(station_id, actor.organization_id, code, data, api_key_hash, now)
    await audit.record(_entry(actor, station.id, "create", None, station.snapshot(), now))
    return IssuedStation(station, api_key)


async def update_station(
    actor: Actor,
    station_id: UUID,
    data: StationData,
    *,
    stations: StationRepository,
    audit: AuditLog,
    clock: Clock,
) -> Station:
    current = await stations.get(actor.organization_id, station_id, for_update=True)
    if current is None:
        raise StationNotFoundError(station_id)
    if current.data == data:
        return current
    await _check_zones(actor, data, stations)
    updated = await stations.replace(actor.organization_id, station_id, data)
    now = clock.now()
    await audit.record(
        _entry(actor, station_id, "update", current.snapshot(), updated.snapshot(), now)
    )
    return updated


async def deactivate_station(
    actor: Actor,
    station_id: UUID,
    *,
    stations: StationRepository,
    audit: AuditLog,
    clock: Clock,
) -> None:
    """Deactivate: ingestion rejects its batches with 403 and its history is kept."""
    current = await stations.get(actor.organization_id, station_id, for_update=True)
    if current is None:
        raise StationNotFoundError(station_id)
    if current.data.status is StationStatus.INACTIVE:
        return
    updated = await stations.replace(
        actor.organization_id, station_id, replace(current.data, status=StationStatus.INACTIVE)
    )
    await audit.record(
        _entry(actor, station_id, "deactivate", current.snapshot(), updated.snapshot(), clock.now())
    )


async def rotate_api_key(
    actor: Actor,
    station_id: UUID,
    *,
    stations: StationRepository,
    issuer: ApiKeyIssuer,
    audit: AuditLog,
    clock: Clock,
) -> IssuedStation:
    """The previous key stops working immediately: only the new key's hash remains."""
    current = await stations.get(actor.organization_id, station_id, for_update=True)
    if current is None:
        raise StationNotFoundError(station_id)
    now = clock.now()
    # Argon2id takes tens of ms: run it in a thread to keep the event loop free.
    api_key, api_key_hash = await asyncio.to_thread(issuer.issue, station_id)
    station = await stations.set_api_key_hash(actor.organization_id, station_id, api_key_hash, now)
    await audit.record(
        _entry(
            actor,
            station_id,
            "rotate_api_key",
            {"api_key_rotated_at": current.api_key_rotated_at.isoformat()},
            {"api_key_rotated_at": now.isoformat()},
            now,
        )
    )
    return IssuedStation(station, api_key)


async def _check_zones(actor: Actor, data: StationData, stations: StationRepository) -> None:
    check_zones(data.zones)
    wanted = {z.zone_id for z in data.zones}
    # A zone from another organization counts as unknown: the message does not reveal it.
    unknown = wanted - await stations.zones_of(actor.organization_id, wanted)
    if unknown:
        raise InvalidStationError("zones", f"zonas desconocidas: {sorted(str(z) for z in unknown)}")


def _entry(
    actor: Actor,
    station_id: UUID,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any],
    at: datetime,
) -> AuditEntry:
    return AuditEntry(
        organization_id=actor.organization_id,
        actor_id=actor.user_id,
        entity_type=ENTITY_TYPE,
        entity_id=station_id,
        action=action,
        before=before,
        after=after,
        at=at,
    )
