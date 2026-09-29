"""IncidentStore en memoria para tests unitarios: deduplica por causa como Postgres."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from vigia.incidents.application.open_incident import OpenResult, OpenStatus, Trigger
from vigia.incidents.application.station_recovery import Recovery


class FakeIncidentStore:
    def __init__(self, *, cooling_down: bool = False, recovered_before: bool = False) -> None:
        self.cooling_down = cooling_down  # toda causa está en enfriamiento
        self.recovered_before = recovered_before  # otro worker ya anotó la recuperación
        self.opened: list[Trigger] = []
        self.recovered: list[tuple[Recovery, datetime]] = []
        self._active: dict[str, UUID] = {}

    async def open(self, tx: Any, trigger: Trigger, now: datetime) -> OpenResult:
        if self.cooling_down:
            return OpenResult(OpenStatus.COOLING_DOWN, None)
        if trigger.dedup_key in self._active:
            return OpenResult(OpenStatus.ACTIVE, self._active[trigger.dedup_key])
        incident_id = uuid4()
        self._active[trigger.dedup_key] = incident_id
        self.opened.append(trigger)
        return OpenResult(OpenStatus.OPENED, incident_id)

    async def record_recovery(self, tx: Any, recovery: Recovery, now: datetime) -> bool:
        self.recovered.append((recovery, now))
        return not self.recovered_before
