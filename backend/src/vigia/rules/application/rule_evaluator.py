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

from vigia.incidents.application.open_incident import (
    IncidentStore,
    Trigger,
    TriggerOutcome,
    record_trigger,
)
from vigia.incidents.domain.incidents import EvidenceReading, Worsening, dedup_key
from vigia.rules.application.queue import QueuedReading
from vigia.rules.domain.errors import InvalidRuleParamsError
from vigia.rules.domain.rate_of_change import Direction, detect_change, parse_rate_of_change
from vigia.rules.domain.threshold import Operator, fires, parse_threshold
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
    cooldown_s: int


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

    async def ok_between(
        self, tx: AsyncConnection, station_id: UUID, since: datetime, until: datetime
    ) -> list[EvidenceReading]:
        """Las lecturas `ok` con since <= measured_at <= until, en orden cronológico."""
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
            recorded = await record_trigger(self._incidents, tx, trigger, self._clock.now())
            incident = str(recorded.incident_id)
            if recorded.outcome is TriggerOutcome.OPENED:
                bound.info("incident_opened", incident_id=incident)
            elif recorded.outcome is TriggerOutcome.READING_ADDED:
                bound.info("incident_reading_added", incident_id=incident)

    async def _check(
        self, tx: AsyncConnection, rule: ApplicableRule, item: QueuedReading
    ) -> Trigger | None:
        match rule.type:
            case "threshold":
                return await self._check_threshold(tx, rule, item)
            case "rate_of_change":
                return await self._check_rate_of_change(tx, rule, item)
            case _:
                return None

    async def _check_threshold(
        self, tx: AsyncConnection, rule: ApplicableRule, item: QueuedReading
    ) -> Trigger | None:
        params = parse_threshold(rule.params)
        recent = await self._history.latest_ok(
            tx, item.station_id, item.measured_at, params.consecutive
        )
        if not fires(params, [r.value for r in recent]):
            return None
        # Un umbral superior (gt, ge) se agrava hacia arriba; uno inferior, hacia abajo.
        upper = params.operator in (Operator.GT, Operator.GE)
        worsening = Worsening.HIGHER if upper else Worsening.LOWER
        return _trigger(rule, item, recent[0], tuple(reversed(recent)), worsening)  # cronológico

    async def _check_rate_of_change(
        self, tx: AsyncConnection, rule: ApplicableRule, item: QueuedReading
    ) -> Trigger | None:
        params = parse_rate_of_change(rule.params)
        # La ventana termina en la lectura evaluada, no en "ahora": una lectura que llega
        # con retraso (sin ser tardía) se evalúa con las lecturas de su momento.
        window = await self._history.ok_between(
            tx, item.station_id, item.measured_at - params.window, item.measured_at
        )
        change = detect_change(params, [r.value for r in window])
        if change is None:
            return None
        # Evidencia: la ventana completa, con el antes y el después de la variación. El
        # valor disparador es la lectura que completó la caída o la subida, y una caída se
        # agrava con valores más bajos.
        down = params.direction is Direction.DOWN
        worsening = Worsening.LOWER if down else Worsening.HIGHER
        return _trigger(rule, item, window[change.end], tuple(window), worsening)


def _trigger(
    rule: ApplicableRule,
    item: QueuedReading,
    trigger_reading: EvidenceReading,
    evidence: tuple[EvidenceReading, ...],
    worsening: Worsening,
) -> Trigger:
    return Trigger(
        organization_id=rule.organization_id,
        zone_id=rule.zone_id,
        rule_id=rule.id,
        rule_type=rule.type,
        rule_params=rule.params,
        severity=rule.severity,
        station_id=item.station_id,
        trigger_reading=trigger_reading,
        dedup_key=dedup_key(rule.id, rule.zone_id),
        cooldown_s=rule.cooldown_s,
        evidence=evidence,
        worsening=worsening,
    )
