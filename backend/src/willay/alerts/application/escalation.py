"""One cycle of the escalation worker (VIG-24).

Each incident is handled in its own transaction, locked with SKIP LOCKED: two workers never
escalate the same incident, and one held elsewhere (e.g. being acknowledged) is retried next
cycle. The lock re-checks it is still open, so an earlier acknowledgement stops escalation.
If the new level reaches nobody, it keeps climbing in the same transaction.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from willay.alerts.application.planning import IncidentAlerting
from willay.alerts.domain.escalation import LevelState, Step, decide
from willay.shared.clock import Clock
from willay.shared.db import Transaction

log = structlog.get_logger()


class EscalationRepository(Protocol):
    async def due(self, tx: AsyncConnection, now: datetime, limit: int) -> list[UUID]:
        """Open, non-exhausted incidents whose current level has expired."""
        ...

    async def lock(self, tx: AsyncConnection, incident_id: UUID) -> LevelState | None:
        """Its level against the current policy, locked. None if another process holds it
        or it is no longer open (acknowledged or resolved)."""
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
    escalated: int  # level moves (one incident may move more than once)
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
                payload = {"level": state.current_level, **decision.payload()}
                await self._repository.record(tx, incident_id, "escalation_exhausted", payload, now)
                bound.warning("escalation_exhausted", reason=decision.reason)
                return moves, 1

            to_level = state.next_level
            await self._repository.move_to_level(tx, incident_id, to_level, now)
            payload = {
                "from_level": state.current_level,
                "to_level": to_level,
                **decision.payload(),
            }
            await self._repository.record(tx, incident_id, "escalated", payload, now)
            alerted = await self._alerts.alert_level(tx, incident_id, to_level, now)
            bound.info("incident_escalated", to_level=to_level, alerts_pending=alerted.pending)
            moves += 1
            # Re-read with the new level: if it reached nobody, it expires immediately.
            state = await self._repository.lock(tx, incident_id)
        return moves, 0
