"""Risk zone SQL repository (vigia_app role). Every query filters by tenant."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection

from vigia.territory.application.zones import Zone
from vigia.territory.domain.zones import (
    MultiPolygonCoords,
    RiskLevel,
    ZoneData,
    to_geojson,
    to_multipolygon,
)

_COLUMNS = """
    id, name, description, risk_level, population_estimate, is_active,
    ST_AsGeoJSON(geom) AS geometry, created_at, updated_at
"""
_GEOM = "ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326))"


class SqlZoneRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def invalid_reason(self, geometry: MultiPolygonCoords) -> str | None:
        reason = await self._conn.scalar(
            text("""
                SELECT CASE
                    WHEN NOT ST_IsValid(g) THEN ST_IsValidReason(g)
                    WHEN ST_Area(g) = 0 THEN 'la geometría no tiene área'
                END
                FROM (SELECT ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326) AS g) AS t
            """),
            {"geometry": json.dumps(to_geojson(geometry))},
        )
        return str(reason) if reason is not None else None

    async def add(
        self, zone_id: UUID, organization_id: UUID, data: ZoneData, now: datetime
    ) -> Zone:
        row = (
            await self._conn.execute(
                text(f"""
                    INSERT INTO core.risk_zones (id, organization_id, name, description,
                                                 risk_level, geom, population_estimate,
                                                 is_active, created_at, updated_at)
                    VALUES (:id, :organization_id, :name, :description, :risk_level, {_GEOM},
                            :population_estimate, :is_active, :now, :now)
                    RETURNING {_COLUMNS}
                """),
                {"id": zone_id, "organization_id": organization_id, "now": now, **_params(data)},
            )
        ).one()
        return _zone(row)

    async def get(
        self, organization_id: UUID, zone_id: UUID, *, for_update: bool = False
    ) -> Zone | None:
        lock = "FOR UPDATE" if for_update else ""
        row = (
            await self._conn.execute(
                text(f"""
                    SELECT {_COLUMNS} FROM core.risk_zones
                    WHERE organization_id = :organization_id AND id = :id {lock}
                """),
                {"organization_id": organization_id, "id": zone_id},
            )
        ).one_or_none()
        return _zone(row) if row is not None else None

    async def list(self, organization_id: UUID, *, include_inactive: bool) -> list[Zone]:
        rows = await self._conn.execute(
            text(f"""
                SELECT {_COLUMNS} FROM core.risk_zones
                WHERE organization_id = :organization_id AND (is_active OR :include_inactive)
                ORDER BY name, id
            """),
            {"organization_id": organization_id, "include_inactive": include_inactive},
        )
        return [_zone(row) for row in rows]

    async def replace(
        self, organization_id: UUID, zone_id: UUID, data: ZoneData, now: datetime
    ) -> Zone:
        row = (
            await self._conn.execute(
                text(f"""
                    UPDATE core.risk_zones
                    SET name = :name, description = :description, risk_level = :risk_level,
                        geom = {_GEOM}, population_estimate = :population_estimate,
                        is_active = :is_active, updated_at = :now
                    WHERE organization_id = :organization_id AND id = :id
                    RETURNING {_COLUMNS}
                """),
                {"organization_id": organization_id, "id": zone_id, "now": now, **_params(data)},
            )
        ).one()
        return _zone(row)


def _params(data: ZoneData) -> dict[str, Any]:
    return {
        "name": data.name,
        "description": data.description,
        "risk_level": data.risk_level.value,
        "population_estimate": data.population_estimate,
        "is_active": data.is_active,
        "geometry": json.dumps(to_geojson(data.geometry)),
    }


def _zone(row: Row[Any]) -> Zone:
    return Zone(
        id=row.id,
        data=ZoneData(
            name=row.name,
            description=row.description,
            risk_level=RiskLevel(row.risk_level),
            population_estimate=row.population_estimate,
            geometry=to_multipolygon(json.loads(row.geometry)),
            is_active=row.is_active,
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
