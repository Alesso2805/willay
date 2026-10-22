"""Readings and the opening evidence of an incident's station, for its chart (VIG-26)."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, NamedTuple
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from willay.incidents.domain.chart import Point

# Only `ok` readings: the ones rules evaluate (late ones never enter a rule's window).
_READINGS = text("""
    SELECT measured_at, value FROM ingest.readings
    WHERE organization_id = :organization_id AND station_id = :station_id AND quality = 'ok'
      AND measured_at BETWEEN :start AND :end
    ORDER BY measured_at
    LIMIT :limit
""")

_STATION = text("""
    SELECT code, unit FROM core.stations WHERE organization_id = :organization_id AND id = :id
""")

_OPENED = text("""
    SELECT payload FROM core.incident_events
    WHERE incident_id = :incident_id AND event_type = 'opened'
    ORDER BY id
    LIMIT 1
""")

# Three hours at the fastest allowed interval (5 s) is 2160 readings.
MAX_POINTS = 5000


class StationLabel(NamedTuple):
    code: str
    unit: str


class SqlIncidentReadings:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def window(
        self, organization_id: UUID, station_id: UUID, start: datetime, end: datetime
    ) -> list[Point]:
        rows = await self._conn.execute(
            _READINGS,
            {
                "organization_id": organization_id,
                "station_id": station_id,
                "start": start,
                "end": end,
                "limit": MAX_POINTS,
            },
        )
        return [Point(r.measured_at, r.value) for r in rows]

    async def station(self, organization_id: UUID, station_id: UUID) -> StationLabel | None:
        params = {"organization_id": organization_id, "id": station_id}
        row = (await self._conn.execute(_STATION, params)).first()
        return StationLabel(row.code, row.unit) if row else None

    async def opened_payload(self, incident_id: UUID) -> Mapping[str, Any]:
        payload: Mapping[str, Any] | None = await self._conn.scalar(
            _OPENED, {"incident_id": incident_id}
        )
        return payload or {}
