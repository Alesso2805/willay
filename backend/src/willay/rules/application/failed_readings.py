"""Readings the evaluator gave up on (VIG-39): after MAX_ATTEMPTS a queue row gets `failed_at`
and leaves the queue so it does not block it (ADR-0002). Each one may be an alert that did not
go out, so operators see them and, once the cause is fixed, send them back to the queue.

Reprocessing is audited per station (audit_log identifies entities by uuid; queue rows have a
bigint id), listing the measurements it sent back and the error each one had.
"""

from dataclasses import dataclass
from datetime import datetime
from itertools import groupby
from typing import Protocol
from uuid import UUID

from willay.rules.application.actor import Actor
from willay.shared.audit import AuditEntry, AuditLog
from willay.shared.clock import Clock

ENTITY_TYPE = "station"
ACTION = "readings_reprocessed"
MAX_LISTED = 500
MAX_REPROCESSED = 500


@dataclass(frozen=True)
class FailedReading:
    id: int  # the queue row
    station_id: UUID
    station_code: str
    station_name: str
    measured_at: datetime
    value: float | None  # None once the reading itself expired (retention)
    unit: str
    attempts: int
    failed_at: datetime
    last_error: str | None


class FailedReadingRepository(Protocol):
    async def all_of(self, organization_id: UUID, *, limit: int) -> list[FailedReading]:
        """Most recent failure first."""
        ...

    async def count(self, organization_id: UUID) -> int: ...

    async def requeue(
        self, organization_id: UUID, ids: frozenset[int], now: datetime
    ) -> list[FailedReading]:
        """Sends the organization's failed rows among `ids` back to the queue (available now,
        attempts from zero) and wakes the evaluator. Returns them as they were before; ids
        that are not failed or not the organization's are ignored."""
        ...


async def reprocess(
    actor: Actor,
    ids: frozenset[int],
    *,
    readings: FailedReadingRepository,
    audit: AuditLog,
    clock: Clock,
) -> list[FailedReading]:
    now = clock.now()
    requeued = await readings.requeue(actor.organization_id, ids, now)
    by_station = sorted(requeued, key=lambda r: (str(r.station_id), r.measured_at))
    for station_id, rows in groupby(by_station, key=lambda r: r.station_id):
        await audit.record(
            AuditEntry(
                organization_id=actor.organization_id,
                actor_id=actor.user_id,
                entity_type=ENTITY_TYPE,
                entity_id=station_id,
                action=ACTION,
                before=None,
                after={
                    "readings": [
                        {
                            "measured_at": r.measured_at.isoformat(),
                            "attempts": r.attempts,
                            "last_error": r.last_error,
                        }
                        for r in rows
                    ]
                },
                at=now,
            )
        )
    return requeued
