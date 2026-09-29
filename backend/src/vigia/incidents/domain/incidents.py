"""Incidentes: causa (dedup_key), evidencia de apertura y lecturas que lo agravan.

Un solo incidente activo por causa (SPEC): `rule_id:zone_id` para umbral y tasa de
cambio; `rule_id:zone_id:station_id` para silencio (un incidente por estación callada).

Mientras el incidente está activo, una lectura que sigue disparando la regla se agrega a
su línea de tiempo (`reading_added`) solo si empeora el valor disparador: un nuevo máximo
en un umbral superior, un nuevo mínimo en una caída. Así la línea de tiempo cuenta cómo
se agravó el evento sin repetir cada lectura; la serie completa sigue en las lecturas.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


def dedup_key(rule_id: UUID, zone_id: UUID, station_id: UUID | None = None) -> str:
    base = f"{rule_id}:{zone_id}"
    return f"{base}:{station_id}" if station_id is not None else base


@dataclass(frozen=True)
class EvidenceReading:
    measured_at: datetime
    value: float


class Worsening(StrEnum):
    """Hacia dónde empeora el valor disparador de una regla."""

    HIGHER = "higher"
    LOWER = "lower"

    def is_worse(self, candidate: float, worst_so_far: float) -> bool:
        """Estricto: igualar el peor valor no lo empeora (reprocesar una lectura no
        duplica eventos)."""
        if self is Worsening.HIGHER:
            return candidate > worst_so_far
        return candidate < worst_so_far
