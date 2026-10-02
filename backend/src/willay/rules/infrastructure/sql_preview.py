"""PreviewRepository over core.stations and ingest.readings (VIG-27)."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncConnection

from willay.rules.application.preview import PreviewStation
from willay.rules.domain.preview import Point

# An `ok` reading arrives at most an hour after it was measured (later ones are `late`), so a
# measured_at bound lets Timescale skip chunks when filtering by received_at.
_MAX_DELAY = timedelta(hours=1)

_ZONE_EXISTS = text("""
    SELECT EXISTS (SELECT 1 FROM core.risk_zones
                   WHERE organization_id = :organization_id AND id = :id)
""")
_COLUMNS = "s.id, s.code, s.name, s.unit, s.expected_interval_s, s.silence_multiplier"
_ONE_STATION = text(f"""
    SELECT {_COLUMNS} FROM core.stations s
    JOIN core.zone_stations zs ON zs.station_id = s.id AND zs.zone_id = :zone_id
    WHERE s.organization_id = :organization_id AND s.id = :station_id
""")
_ZONE_STATIONS = text(f"""
    SELECT {_COLUMNS} FROM core.stations s
    JOIN core.zone_stations zs ON zs.station_id = s.id AND zs.zone_id = :zone_id
    WHERE s.organization_id = :organization_id AND s.status = 'active'
    ORDER BY s.code
""")
_READINGS = text("""
    SELECT measured_at, value FROM ingest.readings
    WHERE station_id = :station_id AND quality = 'ok'
      AND measured_at >= :since AND measured_at <= :until
    ORDER BY measured_at DESC
    LIMIT :limit
""")
_LAST_REPORTED = text("""
    SELECT received_at FROM ingest.readings
    WHERE station_id = :station_id AND quality = 'ok' AND measured_at < :moment
    ORDER BY measured_at DESC
    LIMIT 1
""")
_REPORTED = text("""
    SELECT DISTINCT received_at FROM ingest.readings
    WHERE station_id = :station_id AND quality = 'ok'
      AND measured_at >= :earliest AND received_at >= :since AND received_at <= :until
    ORDER BY received_at
""")


class SqlPreviewRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def zone_exists(self, organization_id: UUID, zone_id: UUID) -> bool:
        params = {"organization_id": organization_id, "id": zone_id}
        return bool(await self._conn.scalar(_ZONE_EXISTS, params))

    async def stations(
        self, organization_id: UUID, zone_id: UUID, station_id: UUID | None
    ) -> list[PreviewStation]:
        params: dict[str, Any] = {"organization_id": organization_id, "zone_id": zone_id}
        if station_id is None:
            rows = await self._conn.execute(_ZONE_STATIONS, params)
        else:
            rows = await self._conn.execute(_ONE_STATION, params | {"station_id": station_id})
        return [_station(r) for r in rows]

    async def readings(
        self, station_id: UUID, since: datetime, until: datetime, limit: int
    ) -> list[Point]:
        rows = await self._conn.execute(
            _READINGS, {"station_id": station_id, "since": since, "until": until, "limit": limit}
        )
        return [Point(r.measured_at, r.value) for r in reversed(rows.all())]

    async def last_reported_before(self, station_id: UUID, moment: datetime) -> datetime | None:
        params = {"station_id": station_id, "moment": moment}
        received: datetime | None = await self._conn.scalar(_LAST_REPORTED, params)
        return received

    async def reported(self, station_id: UUID, since: datetime, until: datetime) -> list[datetime]:
        rows = await self._conn.execute(
            _REPORTED,
            {
                "station_id": station_id,
                "earliest": since - _MAX_DELAY,
                "since": since,
                "until": until,
            },
        )
        return [r.received_at for r in rows]


def _station(r: Row[Any]) -> PreviewStation:
    return PreviewStation(r.id, r.code, r.name, r.unit, r.expected_interval_s, r.silence_multiplier)
