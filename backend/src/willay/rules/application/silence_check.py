"""One cycle of the silence worker (VIG-17): watched stations → silence incidents.

A silence rule watches a station if the rule, its zone and the station are active, the station
is assigned to that zone (a station without a zone never alerts) and the rule targets that
station or the whole zone. One incident per silent station (cause `rule_id:zone_id:station_id`).
The same cycle records station_recovered on active silence incidents whose station has a
heartbeat newer than the one known at opening; the operator still resolves them.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection
from uuid_utils.compat import uuid7

from willay.alerts.application.planning import FIRST_LEVEL, IncidentAlerting
from willay.incidents.application.open_incident import (
    IncidentStore,
    Trigger,
    TriggerOutcome,
    record_trigger,
)
from willay.incidents.application.station_recovery import Recovery, RecoveryLog
from willay.incidents.domain.incidents import EvidenceReading, dedup_key
from willay.rules.application.evaluate import Transaction
from willay.rules.domain.silence import is_silent, silence_threshold
from willay.shared.clock import Clock

log = structlog.get_logger()


@dataclass(frozen=True)
class WatchedStation:
    """A station watched by a silence rule, with its last heartbeat."""

    rule_id: UUID
    organization_id: UUID
    zone_id: UUID
    rule_params: Mapping[str, Any]
    severity: str
    cooldown_s: int
    station_id: UUID
    expected_interval_s: int
    silence_multiplier: int
    last_seen_at: datetime | None  # None: the station never reported
    last_measured_at: datetime | None
    last_value: float | None

    @property
    def threshold(self) -> timedelta:
        return silence_threshold(self.expected_interval_s, self.silence_multiplier)


class SilenceRepository(Protocol):
    async def watched(self, tx: AsyncConnection) -> list[WatchedStation]:
        """All stations watched by silence rules (see module)."""
        ...

    async def recoveries(self, tx: AsyncConnection) -> list[Recovery]:
        """Active silence incidents without station_recovered whose station reported again
        after they opened."""
        ...


class SilenceIncidents(IncidentStore, RecoveryLog, Protocol):
    """What the silence worker does with incidents: open them and record recoveries."""


@dataclass(frozen=True)
class SilenceCycle:
    watched: int
    silent: int
    opened: int
    recovered: int


class SilenceChecker:
    def __init__(
        self,
        repository: SilenceRepository,
        incidents: SilenceIncidents,
        clock: Clock,
        transaction: Transaction,
        *,
        alerts: IncidentAlerting,
    ) -> None:
        self._repository = repository
        self._incidents = incidents
        self._clock = clock
        self._transaction = transaction
        self._alerts = alerts

    async def run(self) -> SilenceCycle:
        now = self._clock.now()
        async with self._transaction() as tx:
            watched = await self._repository.watched(tx)
            recoveries = await self._repository.recoveries(tx)
        silent = [w for w in watched if is_silent(w.last_seen_at, w.threshold, now)]

        opened = 0
        for station in silent:
            # No reading opens a silence incident: it gets a correlation id of its own, which
            # its alerts carry too (VIG-28).
            correlation_id = uuid7()
            with structlog.contextvars.bound_contextvars(correlation_id=str(correlation_id)):
                # One transaction per station: if one fails, the others still open theirs.
                async with self._transaction() as tx:
                    trigger = _trigger(station, correlation_id)
                    recorded = await record_trigger(self._incidents, tx, trigger, now)
                    if (
                        recorded.outcome is TriggerOutcome.OPENED
                        and recorded.incident_id is not None
                    ):
                        await self._alerts.alert_level(tx, recorded.incident_id, FIRST_LEVEL, now)
                if recorded.outcome is TriggerOutcome.OPENED:
                    opened += 1
                    log.info(
                        "incident_opened",
                        rule_type="silence",
                        rule_id=str(station.rule_id),
                        station_id=str(station.station_id),
                        incident_id=str(recorded.incident_id),
                    )

        recovered = 0
        for recovery in recoveries:
            async with self._transaction() as tx:
                first = await self._incidents.record_recovery(tx, recovery, now)
            if first:  # False: another worker recorded it first
                recovered += 1
                log.info(
                    "station_recovered",
                    station_id=str(recovery.station_id),
                    incident_id=str(recovery.incident_id),
                )
        return SilenceCycle(len(watched), len(silent), opened, recovered)


def _trigger(station: WatchedStation, correlation_id: UUID) -> Trigger:
    last_seen = station.last_seen_at
    last_reading = None
    if station.last_measured_at is not None and station.last_value is not None:
        # The last known reading before the silence.
        last_reading = EvidenceReading(station.last_measured_at, station.last_value)
    return Trigger(
        organization_id=station.organization_id,
        zone_id=station.zone_id,
        rule_id=station.rule_id,
        rule_type="silence",
        rule_params=station.rule_params,
        severity=station.severity,
        station_id=station.station_id,
        trigger_reading=last_reading,
        dedup_key=dedup_key(station.rule_id, station.zone_id, station.station_id),
        cooldown_s=station.cooldown_s,
        evidence=(last_reading,) if last_reading is not None else (),
        details={
            "last_seen_at": last_seen.isoformat() if last_seen is not None else None,
            "expected_interval_s": station.expected_interval_s,
            "silence_multiplier": station.silence_multiplier,
        },
        correlation_id=correlation_id,
    )
