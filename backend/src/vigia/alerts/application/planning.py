"""Crear las alertas de un nivel de escalamiento (VIG-20; VIG-24 lo usa para subir de nivel).

Al abrirse un incidente se crean, en la misma transacción, las alertas del nivel 1 de la
política de su regla: una por contacto y canal, aunque el contacto esté en dos grupos
del nivel. Las que se pueden enviar quedan pendientes para el dispatcher, que despierta
con NOTIFY al confirmarse la transacción; las demás quedan omitidas, con su evento
`alert_skipped` en la línea de tiempo del incidente.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from vigia.alerts.domain.alerts import SKIP_REASON, AlertStatus, Target

FIRST_LEVEL = 1


@dataclass(frozen=True)
class LevelAlerts:
    pending: int
    skipped: int


class AlertRepository(Protocol):
    async def targets(
        self, tx: AsyncConnection, incident_id: UUID, level_order: int
    ) -> list[Target]:
        """Contactos del nivel (uno por contacto y canal) con su destino."""
        ...

    async def add(
        self,
        tx: AsyncConnection,
        incident_id: UUID,
        level_order: int,
        targets: Sequence[Target],
        now: datetime,
    ) -> None:
        """Una alerta por destino, en el estado inicial que le corresponde."""
        ...

    async def record_skipped(
        self,
        tx: AsyncConnection,
        incident_id: UUID,
        level_order: int,
        target: Target,
        reason: str,
        now: datetime,
    ) -> None:
        """Evento `alert_skipped` (sin el destino: es un dato personal)."""
        ...

    async def wake_dispatcher(self, tx: AsyncConnection) -> None:
        """NOTIFY al dispatcher; se entrega solo si `tx` confirma."""
        ...


class IncidentAlerting(Protocol):
    """Lo que el evaluador y el worker silence necesitan: alertar un nivel."""

    async def alert_level(
        self, tx: AsyncConnection, incident_id: UUID, level_order: int, now: datetime
    ) -> LevelAlerts: ...


class AlertPlanner:
    def __init__(self, alerts: AlertRepository) -> None:
        self._alerts = alerts

    async def alert_level(
        self, tx: AsyncConnection, incident_id: UUID, level_order: int, now: datetime
    ) -> LevelAlerts:
        targets = await self._alerts.targets(tx, incident_id, level_order)
        await self._alerts.add(tx, incident_id, level_order, targets, now)
        skipped = [t for t in targets if t.initial_status is AlertStatus.SKIPPED]
        for target in skipped:
            reason = SKIP_REASON[target.channel]
            await self._alerts.record_skipped(tx, incident_id, level_order, target, reason, now)
        pending = len(targets) - len(skipped)
        if pending:
            await self._alerts.wake_dispatcher(tx)
        return LevelAlerts(pending=pending, skipped=len(skipped))
