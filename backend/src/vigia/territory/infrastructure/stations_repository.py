"""Station SQL repository (vigia_app role). Every query filters by tenant."""

import json
from collections.abc import Collection
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from vigia.territory.application.stations import (
    DuplicateStationCodeError,
    Heartbeat,
    Station,
)
from vigia.territory.domain.stations import (
    Location,
    Source,
    StationData,
    StationStatus,
    Variable,
    ZoneAssignment,
    ZonePosition,
)

# Dashboard read: station + zones + heartbeat. Ingestion writes the heartbeat; this only reads
# it (the single, read-only crossing into the ingest schema).
_SELECT = """
    SELECT s.id, s.code, s.name, s.variable, ST_X(s.location) AS lon, ST_Y(s.location) AS lat,
           s.source, s.expected_interval_s, s.silence_multiplier, s.status,
           s.api_key_rotated_at, s.created_at,
           h.last_seen_at, h.last_measured_at, h.last_value,
           COALESCE(
               json_agg(json_build_object('zone_id', zs.zone_id, 'position', zs.position)
                        ORDER BY zs.zone_id) FILTER (WHERE zs.zone_id IS NOT NULL),
               '[]'
           ) AS zones
    FROM core.stations s
    LEFT JOIN ingest.station_heartbeats h ON h.station_id = s.id
    LEFT JOIN core.zone_stations zs ON zs.station_id = s.id
"""
_GROUP = " GROUP BY s.id, h.station_id "
# Name Postgres gave UNIQUE (organization_id, code) in migration 0002.
_UNIQUE_CODE = "stations_organization_id_code_key"


class SqlStationRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def zones_of(self, organization_id: UUID, zone_ids: Collection[UUID]) -> set[UUID]:
        if not zone_ids:
            return set()
        rows = await self._conn.execute(
            text("""
                SELECT id FROM core.risk_zones
                WHERE organization_id = :organization_id AND id = ANY(:ids)
            """),
            {"organization_id": organization_id, "ids": list(zone_ids)},
        )
        return {row.id for row in rows}

    async def add(
        self,
        station_id: UUID,
        organization_id: UUID,
        code: str,
        data: StationData,
        api_key_hash: str,
        now: datetime,
    ) -> Station:
        try:
            # SAVEPOINT: on a duplicate code the request transaction stays usable and the
            # error becomes a 409 instead of aborting it.
            async with self._conn.begin_nested():
                await self._conn.execute(
                    text("""
                        INSERT INTO core.stations (id, organization_id, code, name, variable, unit,
                                                   location, source, expected_interval_s,
                                                   silence_multiplier, status, api_key_hash,
                                                   api_key_rotated_at, created_at)
                        VALUES (:id, :organization_id, :code, :name, :variable, :unit,
                                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :source,
                                :expected_interval_s, :silence_multiplier, :status,
                                :api_key_hash, :now, :now)
                    """),
                    {
                        "id": station_id,
                        "organization_id": organization_id,
                        "code": code,
                        "api_key_hash": api_key_hash,
                        "now": now,
                        **_params(data),
                    },
                )
        except IntegrityError as exc:
            # Only this constraint means "duplicate code"; anything else propagates.
            if _UNIQUE_CODE in str(exc.orig):
                raise DuplicateStationCodeError(code) from exc
            raise
        await self._set_zones(station_id, data)
        return await self._get_one(organization_id, station_id)

    async def get(
        self, organization_id: UUID, station_id: UUID, *, for_update: bool = False
    ) -> Station | None:
        if for_update:
            # Lock the station row (not the LEFT JOIN, which FOR UPDATE does not allow).
            locked = await self._conn.scalar(
                text("""
                    SELECT id FROM core.stations
                    WHERE organization_id = :organization_id AND id = :id FOR UPDATE
                """),
                {"organization_id": organization_id, "id": station_id},
            )
            if locked is None:
                return None
        row = (
            await self._conn.execute(
                text(
                    _SELECT + " WHERE s.organization_id = :organization_id AND s.id = :id" + _GROUP
                ),
                {"organization_id": organization_id, "id": station_id},
            )
        ).one_or_none()
        return _station(row) if row is not None else None

    async def list(self, organization_id: UUID, *, include_inactive: bool) -> list[Station]:
        rows = await self._conn.execute(
            text(
                _SELECT
                + """ WHERE s.organization_id = :organization_id
                      AND (s.status = 'active' OR :include_inactive)"""
                + _GROUP
                + " ORDER BY s.code"
            ),
            {"organization_id": organization_id, "include_inactive": include_inactive},
        )
        return [_station(row) for row in rows]

    async def replace(self, organization_id: UUID, station_id: UUID, data: StationData) -> Station:
        await self._conn.execute(
            text("""
                UPDATE core.stations
                SET name = :name, variable = :variable, unit = :unit,
                    location = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), source = :source,
                    expected_interval_s = :expected_interval_s,
                    silence_multiplier = :silence_multiplier, status = :status
                WHERE organization_id = :organization_id AND id = :id
            """),
            {"organization_id": organization_id, "id": station_id, **_params(data)},
        )
        await self._set_zones(station_id, data)
        return await self._get_one(organization_id, station_id)

    async def set_api_key_hash(
        self, organization_id: UUID, station_id: UUID, api_key_hash: str, now: datetime
    ) -> Station:
        await self._conn.execute(
            text("""
                UPDATE core.stations SET api_key_hash = :hash, api_key_rotated_at = :now
                WHERE organization_id = :organization_id AND id = :id
            """),
            {
                "organization_id": organization_id,
                "id": station_id,
                "hash": api_key_hash,
                "now": now,
            },
        )
        return await self._get_one(organization_id, station_id)

    async def _set_zones(self, station_id: UUID, data: StationData) -> None:
        # Full replacement: the submitted list is the truth. The use case already checked
        # the zones belong to the same organization.
        await self._conn.execute(
            text("DELETE FROM core.zone_stations WHERE station_id = :id"), {"id": station_id}
        )
        for zone in data.zones:
            await self._conn.execute(
                text("""
                    INSERT INTO core.zone_stations (zone_id, station_id, position)
                    VALUES (:zone_id, :station_id, :position)
                """),
                {
                    "zone_id": zone.zone_id,
                    "station_id": station_id,
                    "position": zone.position.value,
                },
            )

    async def _get_one(self, organization_id: UUID, station_id: UUID) -> Station:
        station = await self.get(organization_id, station_id)
        assert station is not None
        return station


def _params(data: StationData) -> dict[str, Any]:
    return {
        "name": data.name,
        "variable": data.variable.value,
        "unit": data.unit,
        "lon": data.location.lon,
        "lat": data.location.lat,
        "source": data.source.value,
        "expected_interval_s": data.expected_interval_s,
        "silence_multiplier": data.silence_multiplier,
        "status": data.status.value,
    }


def _station(row: Row[Any]) -> Station:
    zones = row.zones if isinstance(row.zones, list) else json.loads(row.zones)
    heartbeat = (
        Heartbeat(row.last_seen_at, row.last_measured_at, row.last_value)
        if row.last_seen_at is not None
        else None
    )
    return Station(
        id=row.id,
        code=row.code,
        data=StationData(
            name=row.name,
            variable=Variable(row.variable),
            location=Location(row.lon, row.lat),
            source=Source(row.source),
            expected_interval_s=row.expected_interval_s,
            silence_multiplier=row.silence_multiplier,
            status=StationStatus(row.status),
            zones=tuple(
                ZoneAssignment(UUID(z["zone_id"]), ZonePosition(z["position"])) for z in zones
            ),
        ),
        api_key_rotated_at=row.api_key_rotated_at,
        created_at=row.created_at,
        heartbeat=heartbeat,
    )
