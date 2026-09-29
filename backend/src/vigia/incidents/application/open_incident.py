"""Apertura de incidentes desde el evaluador y el worker silence (base de VIG-18).

Lo que falta y llega con VIG-18: enfriamiento (`cooldown_s`), eventos `reading_added`
cuando el incidente ya está abierto y el test de carrera con dos evaluadores.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from vigia.incidents.domain.incidents import EvidenceReading


@dataclass(frozen=True)
class Trigger:
    """Lo que una regla encontró: basta para abrir el incidente y documentar por qué."""

    organization_id: UUID
    zone_id: UUID
    rule_id: UUID
    rule_type: str
    rule_params: Mapping[str, Any]
    severity: str
    station_id: UUID
    # None si no hay valor que mostrar: una estación en silencio sin último valor.
    trigger_value: float | None
    dedup_key: str
    # Copia de las lecturas que dispararon la regla: sobrevive a la retención de 180 días.
    evidence: tuple[EvidenceReading, ...]
    # Contexto propio del tipo de regla, p. ej. el último latido de una estación en silencio.
    details: Mapping[str, Any] = field(default_factory=dict)


class IncidentStore(Protocol):
    async def open(self, tx: AsyncConnection, trigger: Trigger, now: datetime) -> UUID | None:
        """Abre el incidente y su evento `opened` en `tx`. None si ya había uno activo
        con la misma causa (dedup_key)."""
        ...
