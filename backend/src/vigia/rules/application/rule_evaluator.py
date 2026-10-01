"""Worker rule evaluator: applies the station's rules to each reading.

A rule applies if the rule and its zone are active, the station is assigned to that zone (a
station without a zone never alerts, SPEC) and the rule targets that station or the whole zone
(null station_id). A rule with invalid params is skipped and logged: failing the evaluation
would send every reading of the station to failed_at and stop the healthy rules too.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from vigia.alerts.application.planning import FIRST_LEVEL, IncidentAlerting
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
        """Threshold and rate-of-change rules that apply to the station (see module)."""
        ...


class ReadingHistory(Protocol):
    async def latest_ok(
        self, tx: AsyncConnection, station_id: UUID, until: datetime, limit: int
    ) -> list[EvidenceReading]:
        """The `limit` most recent `ok` readings with measured_at <= until, latest first."""
        ...

    async def ok_between(
        self, tx: AsyncConnection, station_id: UUID, since: datetime, until: datetime
    ) -> list[EvidenceReading]:
        """The `ok` readings with since <= measured_at <= until, in chronological order."""
        ...


class RuleEvaluator:
    def __init__(
        self,
        rules: RuleRepository,
        history: ReadingHistory,
        incidents: IncidentStore,
        clock: Clock,
        *,
        alerts: IncidentAlerting,
    ) -> None:
        self._rules = rules
        self._history = history
        self._incidents = incidents
        self._clock = clock
        self._alerts = alerts

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
            now = self._clock.now()
            recorded = await record_trigger(self._incidents, tx, trigger, now)
            incident = str(recorded.incident_id)
            if recorded.outcome is TriggerOutcome.OPENED and recorded.incident_id is not None:
                # Same transaction as the incident: both exist or neither does.
                alerted = await self._alerts.alert_level(tx, recorded.incident_id, FIRST_LEVEL, now)
                bound.info(
                    "incident_opened",
                    incident_id=incident,
                    alerts_pending=alerted.pending,
                    alerts_skipped=alerted.skipped,
                )
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
        upper = params.operator in (Operator.GT, Operator.GE)
        worsening = Worsening.HIGHER if upper else Worsening.LOWER
        return _trigger(rule, item, recent[0], tuple(reversed(recent)), worsening)  # chronological

    async def _check_rate_of_change(
        self, tx: AsyncConnection, rule: ApplicableRule, item: QueuedReading
    ) -> Trigger | None:
        params = parse_rate_of_change(rule.params)
        # The window ends at the evaluated reading, not at "now": a delayed (but not late)
        # reading is evaluated against the readings of its own time.
        window = await self._history.ok_between(
            tx, item.station_id, item.measured_at - params.window, item.measured_at
        )
        change = detect_change(params, [r.value for r in window])
        if change is None:
            return None
        # Evidence is the whole window (before and after the change); the trigger value is
        # the reading that completed the drop or rise.
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
