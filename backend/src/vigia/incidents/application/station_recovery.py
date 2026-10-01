"""station_recovered event: the station of a silence incident is reporting again.

It does not close the incident (SPEC): the operator resolves it, seeing in the timeline when
the signal came back. Recorded once per incident.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class Recovery:
    incident_id: UUID
    organization_id: UUID
    station_id: UUID
    last_seen_at: datetime
    last_measured_at: datetime | None
    last_value: float | None


class RecoveryLog(Protocol):
    async def record_recovery(self, tx: AsyncConnection, recovery: Recovery, now: datetime) -> bool:
        """Records station_recovered in `tx`. False if the incident already had it."""
        ...
