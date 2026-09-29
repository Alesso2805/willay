"""Un ciclo del worker silence (VIG-17): estaciones vigiladas → incidentes de silencio.

Una estación está vigilada por una regla de silencio si la regla y su zona están
activas, la estación está activa y asignada a esa zona (una estación sin zona nunca
alerta) y la regla es de esa estación o de toda la zona. Se abre un incidente por
estación silenciada, con causa `rule_id:zone_id:station_id`: dos estaciones calladas en
la misma zona son dos incidentes.

En el mismo ciclo se registra station_recovered en los incidentes de silencio activos
cuya estación volvió a reportar, es decir, que tiene un latido posterior al que se
conocía al abrirlos. El incidente sigue abierto hasta que el operador lo resuelve.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
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
from vigia.incidents.application.station_recovery import Recovery, RecoveryLog
from vigia.incidents.domain.incidents import EvidenceReading, dedup_key
from vigia.rules.application.evaluate import Transaction
from vigia.rules.domain.silence import is_silent, silence_threshold
from vigia.shared.clock import Clock

log = structlog.get_logger()


@dataclass(frozen=True)
class WatchedStation:
    """Una estación vigilada por una regla de silencio, con su último latido."""

    rule_id: UUID
    organization_id: UUID
    zone_id: UUID
    rule_params: Mapping[str, Any]
    severity: str
    cooldown_s: int
    station_id: UUID
    expected_interval_s: int
    silence_multiplier: int
    last_seen_at: datetime | None  # None: la estación nunca reportó
    last_measured_at: datetime | None
    last_value: float | None

    @property
    def threshold(self) -> timedelta:
        return silence_threshold(self.expected_interval_s, self.silence_multiplier)


class SilenceRepository(Protocol):
    async def watched(self, tx: AsyncConnection) -> list[WatchedStation]:
        """Todas las estaciones vigiladas por reglas de silencio (ver módulo)."""
        ...

    async def recoveries(self, tx: AsyncConnection) -> list[Recovery]:
        """Incidentes de silencio activos, sin station_recovered, cuya estación volvió a
        reportar después de abrirse."""
        ...


class SilenceIncidents(IncidentStore, RecoveryLog, Protocol):
    """Lo que el worker silence hace con los incidentes: abrirlos y anotar recuperaciones."""


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
            # Una transacción por estación: si una falla, las demás abren igual su
            # incidente. Si ya hay uno activo o la causa está en enfriamiento, no se abre.
            async with self._transaction() as tx:
                recorded = await record_trigger(self._incidents, tx, _trigger(station), now)
                if recorded.outcome is TriggerOutcome.OPENED and recorded.incident_id is not None:
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
            if first:  # False: otro worker lo registró primero
                recovered += 1
                log.info(
                    "station_recovered",
                    station_id=str(recovery.station_id),
                    incident_id=str(recovery.incident_id),
                )
        return SilenceCycle(len(watched), len(silent), opened, recovered)


def _trigger(station: WatchedStation) -> Trigger:
    last_seen = station.last_seen_at
    last_reading = None
    if station.last_measured_at is not None and station.last_value is not None:
        # La última lectura conocida antes del silencio.
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
    )
