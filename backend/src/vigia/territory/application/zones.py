"""Casos de uso de zonas de riesgo. Todo filtra por la organización del actor."""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from uuid_utils.compat import uuid7

from vigia.shared.audit import AuditEntry, AuditLog
from vigia.shared.clock import Clock
from vigia.territory.domain.zones import (
    InvalidGeometryError,
    MultiPolygonCoords,
    ZoneData,
    to_geojson,
)

ENTITY_TYPE = "risk_zone"


@dataclass(frozen=True)
class Actor:
    organization_id: UUID  # el tenant: nunca sale del cuerpo de la petición
    user_id: UUID


@dataclass(frozen=True)
class Zone:
    id: UUID
    data: ZoneData
    created_at: datetime
    updated_at: datetime

    def snapshot(self) -> dict[str, Any]:
        """Lo que se guarda en la auditoría: estado completo, geometría incluida."""
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
        """Motivo de PostGIS si la geometría no es válida (autointersección, sin área...)."""
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
    """No existe en la organización del actor (404; también si existe en otra)."""


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
    # FOR UPDATE: dos operadores editando la misma zona no se pisan el "antes" auditado.
    current = await zones.get(actor.organization_id, zone_id, for_update=True)
    if current is None:
        raise ZoneNotFoundError(zone_id)
    if current.data == data:
        return current  # sin cambios: ni escritura ni entrada de auditoría vacía
    await _check_topology(zones, data.geometry)
    now = clock.now()
    updated = await zones.replace(actor.organization_id, zone_id, data, now)
    await audit.record(_entry(actor, zone_id, "update", current, updated, now))
    return updated


async def deactivate_zone(
    actor: Actor, zone_id: UUID, *, zones: ZoneRepository, audit: AuditLog, clock: Clock
) -> None:
    """Desactiva en lugar de borrar: reglas e incidentes guardan referencias a la zona, y
    la historia de un incidente no debe perderse porque alguien quitó su zona."""
    current = await zones.get(actor.organization_id, zone_id, for_update=True)
    if current is None:
        raise ZoneNotFoundError(zone_id)
    if not current.data.is_active:
        return  # idempotente: DELETE dos veces no audita dos veces
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
