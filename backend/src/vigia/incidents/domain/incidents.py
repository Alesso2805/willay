"""Incidentes: causa (dedup_key) y evidencia de apertura.

Un solo incidente activo por causa (SPEC): `rule_id:zone_id` para umbral y tasa de
cambio; `rule_id:zone_id:station_id` para silencio (un incidente por estación callada).
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


def dedup_key(rule_id: UUID, zone_id: UUID, station_id: UUID | None = None) -> str:
    base = f"{rule_id}:{zone_id}"
    return f"{base}:{station_id}" if station_id is not None else base


@dataclass(frozen=True)
class EvidenceReading:
    measured_at: datetime
    value: float
