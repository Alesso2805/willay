"""Evento station_recovered: la estación de un incidente de silencio volvió a reportar.

No cierra el incidente (SPEC): lo resuelve el operador, que ve en la línea de tiempo
cuándo volvió la señal. Se registra una sola vez por incidente.
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
        """Registra station_recovered en `tx`. False si el incidente ya lo tenía."""
        ...
