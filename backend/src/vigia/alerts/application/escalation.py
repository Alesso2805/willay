"""Un ciclo del worker escalation (VIG-24).

Cada incidente se procesa en su propia transacción y bloqueado con SKIP LOCKED: dos
workers nunca escalan el mismo incidente, y si otro proceso lo tiene (por ejemplo, alguien
confirmándolo en ese momento) se revisa en el ciclo siguiente. Dentro de la transacción
se vuelve a comprobar que siga abierto: una confirmación que llegó antes detiene el
escalamiento.

Si el nivel al que sube no puede avisar a nadie, se sigue subiendo en la misma
transacción hasta encontrar un nivel que sí avise o agotar la política.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from vigia.alerts.application.planning import IncidentAlerting
from vigia.alerts.domain.escalation import LevelState, Step, decide
from vigia.rules.application.evaluate import Transaction
from vigia.shared.clock import Clock

log = structlog.get_logger()


class EscalationRepository(Protocol):
    async def due(self, tx: AsyncConnection, now: datetime, limit: int) -> list[UUID]:
        """Incidentes abiertos, sin agotar, cuyo nivel actual ya venció."""
        ...

    async def lock(self, tx: AsyncConnection, incident_id: UUID) -> LevelState | None:
        """Su nivel contra la política vigente, bloqueado. None si otro proceso lo tiene o
        ya no está abierto (lo confirmaron o resolvieron)."""
        ...

    async def move_to_level(
        self, tx: AsyncConnection, incident_id: UUID, level: int, now: datetime
    ) -> None: ...

    async def exhaust(self, tx: AsyncConnection, incident_id: UUID, now: datetime) -> None: ...

    async def record(
        self,
        tx: AsyncConnection,
        incident_id: UUID,
        event_type: str,
        payload: dict[str, Any],
        now: datetime,
    ) -> None: ...


@dataclass(frozen=True)
class EscalationCycle:
    escalated: int  # subidas de nivel (un incidente puede subir más de una vez)
    exhausted: int


class Escalator:
    def __init__(
        self,
        repository: EscalationRepository,
        alerts: IncidentAlerting,
        clock: Clock,
        transaction: Transaction,
    ) -> None:
        self._repository = repository
        self._alerts = alerts
        self._clock = clock
        self._transaction = transaction

    async def run(self, limit: int = 50) -> EscalationCycle:
        now = self._clock.now()
        async with self._transaction() as tx:
            due = await self._repository.due(tx, now, limit)
        escalated = exhausted = 0
        for incident_id in due:
            async with self._transaction() as tx:
                moves, done = await self._escalate(tx, incident_id, now)
            escalated += moves
            exhausted += done
        return EscalationCycle(escalated, exhausted)

    async def _escalate(
        self, tx: AsyncConnection, incident_id: UUID, now: datetime
    ) -> tuple[int, int]:
        moves = 0
        state = await self._repository.lock(tx, incident_id)
        while state is not None:
            decision = decide(state, now)
            bound = log.bind(incident_id=str(incident_id), level=state.current_level)
            if decision.step is Step.WAIT:
                break
            if decision.step is Step.EXHAUST or state.next_level is None:
                await self._repository.exhaust(tx, incident_id, now)
                payload = {"level": state.current_level, "reason": decision.reason}
                await self._repository.record(tx, incident_id, "escalation_exhausted", payload, now)
                bound.warning("escalation_exhausted", reason=decision.reason)
                return moves, 1

            to_level = state.next_level
            await self._repository.move_to_level(tx, incident_id, to_level, now)
            payload = {
                "from_level": state.current_level,
                "to_level": to_level,
                "reason": decision.reason,
            }
            await self._repository.record(tx, incident_id, "escalated", payload, now)
            alerted = await self._alerts.alert_level(tx, incident_id, to_level, now)
            bound.info("incident_escalated", to_level=to_level, alerts_pending=alerted.pending)
            moves += 1
            # Releer con el nivel nuevo: si no pudo avisar a nadie, vence en el acto.
            state = await self._repository.lock(tx, incident_id)
        return moves, 0
