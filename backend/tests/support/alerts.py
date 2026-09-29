"""IncidentAlerting en memoria para tests unitarios: registra qué niveles se alertaron."""

from datetime import datetime
from typing import Any
from uuid import UUID

from vigia.alerts.application.planning import LevelAlerts


class FakeAlerting:
    def __init__(self) -> None:
        self.levels: list[tuple[UUID, int]] = []

    async def alert_level(
        self, tx: Any, incident_id: UUID, level_order: int, now: datetime
    ) -> LevelAlerts:
        self.levels.append((incident_id, level_order))
        return LevelAlerts(pending=1, skipped=0)
