"""A clean slate for the demo organization, before and after each run.

`clear` deletes the organization's operational data: readings, queue, heartbeats, and the
incidents with their events and alerts. Its configuration stays: zones, stations, rules,
policies, contacts (with their Telegram link) and the audit log. Without it, a previous run's
incident would swallow this run's (one active incident per cause) or its cooldown would hold
the new one back. Without heartbeats the stations count as never reported, so Santa Eulalia is
not silent before the scenario silences it.

Both run as willay_owner: willay_app cannot delete incident_events, which stay append-only for
the API and the workers. A demo tool, for the demo organization only.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncConnection

_STATIONS = "SELECT id FROM core.stations WHERE organization_id = :organization_id"

_INCIDENTS = [
    """DELETE FROM core.alerts a USING core.incidents i
       WHERE a.incident_id = i.id AND i.organization_id = :organization_id""",
    "DELETE FROM core.incident_events WHERE organization_id = :organization_id",
]
_DELETE_INCIDENTS = "DELETE FROM core.incidents WHERE organization_id = :organization_id"
_DELETE_QUEUE = "DELETE FROM ingest.evaluation_queue WHERE organization_id = :organization_id"
# By station: the hypertable's primary key starts with station_id.
_DELETE_READINGS = f"DELETE FROM ingest.readings WHERE station_id IN ({_STATIONS})"
_DELETE_HEARTBEATS = f"DELETE FROM ingest.station_heartbeats WHERE station_id IN ({_STATIONS})"


@dataclass(frozen=True)
class Cleared:
    incidents: int
    readings: int


async def clear(conn: AsyncConnection, organization_id: UUID) -> Cleared:
    params = {"organization_id": organization_id}
    for statement in _INCIDENTS:
        await conn.execute(text(statement), params)
    incidents = await _delete(conn, _DELETE_INCIDENTS, params)
    await conn.execute(text(_DELETE_QUEUE), params)
    readings = await _delete(conn, _DELETE_READINGS, params)
    await park(conn, organization_id)
    return Cleared(incidents, readings)


async def park(conn: AsyncConnection, organization_id: UUID) -> None:
    """The stations count as never reported again: once the simulator stops, no silence
    incident opens for them."""
    await conn.execute(text(_DELETE_HEARTBEATS), {"organization_id": organization_id})


async def _delete(conn: AsyncConnection, statement: str, params: dict[str, UUID]) -> int:
    result: CursorResult[tuple[()]] = await conn.execute(text(statement), params)
    return result.rowcount
