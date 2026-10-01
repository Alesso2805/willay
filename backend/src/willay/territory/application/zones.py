"""Risk zone use cases. Everything filters by the actor's organization."""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from uuid_utils.compat import uuid7

from willay.shared.audit import AuditEntry, AuditLog
from willay.shared.clock import Clock
from willay.territory.domain.zones import (
    InvalidGeometryError,
    MultiPolygonCoords,
    ZoneData,
    to_geojson,
)

ENTITY_TYPE = "risk_zone"


@dataclass(frozen=True)
class Actor:
    organization_id: UUID  # the tenant: never taken from the request body
    user_id: UUID


@dataclass(frozen=True)
class Zone:
    id: UUID
    data: ZoneData
    created_at: datetime
    updated_at: datetime

    def snapshot(self) -> dict[str, Any]:
        """What goes into the audit log: full state, geometry included."""
        return {
            "name": self.data.name,
            "description": self.data.description,
            "risk_level": self.data.risk_level.value,
            "population_estimate": self.data.population_estimate,
            "is_active": self.data.is_active,
            "geometry": to_geojson(self.data.geometry),
        }


class ZoneRepository(Protocol):
    async def invalid_reason(self, geometry: MultiPolygonCoords) -> str | None:
        """PostGIS reason if the geometry is invalid (self-intersection, no area...)."""
        ...

    async def add(
        self, zone_id: UUID, organization_id: UUID, data: ZoneData, now: datetime
    ) -> Zone: ...

    async def get(
        self, organization_id: UUID, zone_id: UUID, *, for_update: bool = False
    ) -> Zone | None: ...

    async def list(self, organization_id: UUID, *, include_inactive: bool) -> list[Zone]: ...

    async def replace(
        self, organization_id: UUID, zone_id: UUID, data: ZoneData, now: datetime
    ) -> Zone: ...


class ZoneNotFoundError(Exception):
    """Not found in the actor's organization (404, even if it exists in another one)."""


async def create_zone(
    actor: Actor, data: ZoneData, *, zones: ZoneRepository, audit: AuditLog, clock: Clock
) -> Zone:
    await _check_topology(zones, data.geometry)
    now = clock.now()
    zone = await zones.add(uuid7(), actor.organization_id, data, now)
    await audit.record(_entry(actor, zone.id, "create", None, zone, now))
    return zone


async def update_zone(
    actor: Actor,
    zone_id: UUID,
    data: ZoneData,
    *,
    zones: ZoneRepository,
    audit: AuditLog,
    clock: Clock,
) -> Zone:
    # FOR UPDATE: two operators editing the same zone cannot clobber the audited "before".
    current = await zones.get(actor.organization_id, zone_id, for_update=True)
    if current is None:
        raise ZoneNotFoundError(zone_id)
    if current.data == data:
        return current  # unchanged: no write and no empty audit entry
    await _check_topology(zones, data.geometry)
    now = clock.now()
    updated = await zones.replace(actor.organization_id, zone_id, data, now)
    await audit.record(_entry(actor, zone_id, "update", current, updated, now))
    return updated


async def deactivate_zone(
    actor: Actor, zone_id: UUID, *, zones: ZoneRepository, audit: AuditLog, clock: Clock
) -> None:
    """Deactivate instead of delete: rules and incidents reference the zone, and an
    incident's history must not be lost because someone removed its zone."""
    current = await zones.get(actor.organization_id, zone_id, for_update=True)
    if current is None:
        raise ZoneNotFoundError(zone_id)
    if not current.data.is_active:
        return  # idempotent: a second DELETE is not audited again
    now = clock.now()
    updated = await zones.replace(
        actor.organization_id, zone_id, replace(current.data, is_active=False), now
    )
    await audit.record(_entry(actor, zone_id, "deactivate", current, updated, now))


async def _check_topology(zones: ZoneRepository, geometry: MultiPolygonCoords) -> None:
    reason = await zones.invalid_reason(geometry)
    if reason is not None:
        raise InvalidGeometryError(reason)


def _entry(
    actor: Actor, zone_id: UUID, action: str, before: Zone | None, after: Zone, at: datetime
) -> AuditEntry:
    return AuditEntry(
        organization_id=actor.organization_id,
        actor_id=actor.user_id,
        entity_type=ENTITY_TYPE,
        entity_id=zone_id,
        action=action,
        before=before.snapshot() if before else None,
        after=after.snapshot(),
        at=at,
    )
