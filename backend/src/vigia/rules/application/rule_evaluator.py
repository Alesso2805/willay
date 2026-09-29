"""Evaluador de reglas del worker: aplica las reglas de la estación a cada lectura.

Una regla aplica a la estación si:
- la regla y su zona están activas;
- la estación está asignada a esa zona (una estación sin zona nunca alerta, SPEC);
- la regla es de esa estación o de toda la zona (station_id nulo).

Una regla con parámetros inválidos se salta y se registra: si hiciera fallar la
evaluación, todas las lecturas de la estación acabarían con failed_at y las demás reglas,
sanas, dejarían de evaluarse.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from vigia.incidents.application.open_incident import IncidentStore, Trigger
from vigia.incidents.domain.incidents import EvidenceReading, dedup_key
from vigia.rules.application.queue import QueuedReading
from vigia.rules.domain.threshold import InvalidRuleParamsError, fires, parse_threshold
from vigia.shared.clock import Clock

log = structlog.get_logger()


@dataclass(frozen=True)
class ApplicableRule:
    id: UUID
    organization_id: UUID
    zone_id: UUID
    type: str
    params: Mapping[str, Any]
    severity: str


class RuleRepository(Protocol):
    async def applicable(
        self, tx: AsyncConnection, organization_id: UUID, station_id: UUID
    ) -> list[ApplicableRule]:
        """Reglas de umbral y tasa de cambio que aplican a la estación (ver módulo)."""
        ...


class ReadingHistory(Protocol):
    async def latest_ok(
        self, tx: AsyncConnection, station_id: UUID, until: datetime, limit: int
    ) -> list[EvidenceReading]:
        """Las `limit` lecturas `ok` más recientes con measured_at <= until, la última primero."""
        ...


class RuleEvaluator:
    def __init__(
        self,
        rules: RuleRepository,
        history: ReadingHistory,
        incidents: IncidentStore,
        clock: Clock,
    ) -> None:
        self._rules = rules
        self._history = history
        self._incidents = incidents
        self._clock = clock

    async def evaluate(self, tx: AsyncConnection, item: QueuedReading) -> None:
        for rule in await self._rules.applicable(tx, item.organization_id, item.station_id):
            bound = log.bind(rule_id=str(rule.id), rule_type=rule.type, queue_id=item.queue_id)
            try:
                trigger = await self._check(tx, rule, item)
            except InvalidRuleParamsError as exc:
                bound.error("rule_skipped_invalid_params", error=str(exc))
                continue
            if trigger is None:
                continue
            incident_id = await self._incidents.open(tx, trigger, self._clock.now())
            if incident_id is not None:
                bound.info("incident_opened", incident_id=str(incident_id))

    async def _check(
        self, tx: AsyncConnection, rule: ApplicableRule, item: QueuedReading
    ) -> Trigger | None:
        if rule.type != "threshold":
            return None  # tasa de cambio: VIG-16
        params = parse_threshold(rule.params)
        recent = await self._history.latest_ok(
            tx, item.station_id, item.measured_at, params.consecutive
        )
        if not fires(params, [r.value for r in recent]):
            return None
        return Trigger(
            organization_id=rule.organization_id,
            zone_id=rule.zone_id,
            rule_id=rule.id,
            rule_type=rule.type,
            rule_params=rule.params,
            severity=rule.severity,
            station_id=item.station_id,
            trigger_value=recent[0].value,
            dedup_key=dedup_key(rule.id, rule.zone_id),
            evidence=tuple(reversed(recent)),  # en orden cronológico
        )
