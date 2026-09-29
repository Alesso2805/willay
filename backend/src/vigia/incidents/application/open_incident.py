"""Qué le pasa a un incidente cuando una regla dispara (evaluador y worker silence).

- Sin incidente activo con esa causa, se abre uno con su evento `opened`.
- Si la causa se resolvió hace menos de `cooldown_s`, no se abre otro (enfriamiento). La
  lectura ya quedó guardada en la ingesta: el enfriamiento solo evita el incidente.
- Si ya hay uno activo, se agrega `reading_added` cuando la lectura empeora el valor
  disparador (ver incidents.domain.incidents).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from vigia.incidents.domain.incidents import EvidenceReading, Worsening


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
    # La lectura con el valor disparador; None en una estación en silencio sin último valor.
    trigger_reading: EvidenceReading | None
    dedup_key: str
    cooldown_s: int
    # Copia de las lecturas que dispararon la regla: sobrevive a la retención de 180 días.
    evidence: tuple[EvidenceReading, ...]
    # Contexto propio del tipo de regla, p. ej. el último latido de una estación en silencio.
    details: Mapping[str, Any] = field(default_factory=dict)
    # Hacia dónde se agrava; None si la regla no se agrava con lecturas (silencio).
    worsening: Worsening | None = None

    @property
    def trigger_value(self) -> float | None:
        return self.trigger_reading.value if self.trigger_reading is not None else None


class OpenStatus(StrEnum):
    OPENED = "opened"
    ACTIVE = "active"  # ya había uno activo con la misma causa
    COOLING_DOWN = "cooling_down"  # la causa se resolvió hace menos de cooldown_s


@dataclass(frozen=True)
class OpenResult:
    status: OpenStatus
    incident_id: UUID | None  # el abierto o el activo; None en enfriamiento


class IncidentStore(Protocol):
    async def open(self, tx: AsyncConnection, trigger: Trigger, now: datetime) -> OpenResult:
        """Abre el incidente y su evento `opened` en `tx`, salvo que haya uno activo con la
        misma causa o que la causa esté en enfriamiento."""
        ...

    async def worst_value(self, tx: AsyncConnection, incident_id: UUID) -> float | None:
        """El peor valor registrado (el disparador o el último `reading_added`). Bloquea el
        incidente hasta el final de `tx`: dos evaluadores no lo agravan a la vez."""
        ...

    async def add_reading(
        self,
        tx: AsyncConnection,
        incident_id: UUID,
        organization_id: UUID,
        reading: EvidenceReading,
        now: datetime,
    ) -> None:
        """Agrega el evento `reading_added` con la lectura."""
        ...


class TriggerOutcome(StrEnum):
    OPENED = "opened"
    READING_ADDED = "reading_added"
    UNCHANGED = "unchanged"  # activo y la lectura no lo agrava
    COOLING_DOWN = "cooling_down"


@dataclass(frozen=True)
class Recorded:
    outcome: TriggerOutcome
    incident_id: UUID | None


async def record_trigger(
    store: IncidentStore, tx: AsyncConnection, trigger: Trigger, now: datetime
) -> Recorded:
    result = await store.open(tx, trigger, now)
    if result.status is OpenStatus.OPENED:
        return Recorded(TriggerOutcome.OPENED, result.incident_id)
    if result.status is OpenStatus.COOLING_DOWN or result.incident_id is None:
        return Recorded(TriggerOutcome.COOLING_DOWN, None)

    incident_id, reading, worsening = result.incident_id, trigger.trigger_reading, trigger.worsening
    if reading is None or worsening is None:
        return Recorded(TriggerOutcome.UNCHANGED, incident_id)
    worst = await store.worst_value(tx, incident_id)
    if worst is not None and not worsening.is_worse(reading.value, worst):
        return Recorded(TriggerOutcome.UNCHANGED, incident_id)
    await store.add_reading(tx, incident_id, trigger.organization_id, reading, now)
    return Recorded(TriggerOutcome.READING_ADDED, incident_id)
