"""Creating the alerts of an escalation level (VIG-20; VIG-24 reuses it to move up a level).

Created in the same transaction that opens (or escalates) the incident: one per contact
and channel, even if the contact is in two groups of the level. Sendable ones stay pending
for the dispatcher, woken by NOTIFY on commit; the rest are skipped with an
`alert_skipped` timeline event.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from willay.alerts.domain.alerts import SKIP_REASON, AlertStatus, Reason, Target

FIRST_LEVEL = 1


@dataclass(frozen=True)
class LevelAlerts:
    pending: int
    skipped: int


class AlertRepository(Protocol):
    async def targets(
        self, tx: AsyncConnection, incident_id: UUID, level_order: int
    ) -> list[Target]:
        """The level's contacts (one per contact and channel) with their destination."""
        ...

    async def add(
        self,
        tx: AsyncConnection,
        incident_id: UUID,
        level_order: int,
        targets: Sequence[Target],
        now: datetime,
    ) -> None:
        """One alert per target, in its corresponding initial status."""
        ...

    async def record_skipped(
        self,
        tx: AsyncConnection,
        incident_id: UUID,
        level_order: int,
        target: Target,
        reason: Reason,
        now: datetime,
    ) -> None:
        """`alert_skipped` event (without the destination: it is personal data)."""
        ...

    async def wake_dispatcher(self, tx: AsyncConnection) -> None:
        """NOTIFY to the dispatcher; delivered only if `tx` commits."""
        ...


class IncidentAlerting(Protocol):
    """What the evaluator, the silence worker and the escalation worker need: alerting a
    level."""

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
