"""Use case: store a station's batch of readings and enqueue them for evaluation."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from uuid_utils.compat import uuid7

from willay.ingestion.application.authenticate_station import AuthenticatedStation
from willay.ingestion.domain.readings import (
    ClassifiedReading,
    Reading,
    check_not_in_future,
    classify,
    heartbeat_reading,
)
from willay.shared.clock import Clock


@dataclass(frozen=True)
class StoreCounts:
    stored: int  # new ones; the rest were duplicates by (station_id, measured_at)
    late: int  # of the new ones, how many were late (stored, not enqueued)
    enqueued: int


@dataclass(frozen=True)
class IngestResult:
    received: int
    counts: StoreCounts
    # Follows these readings to the incident they open and its alerts.
    correlation_id: UUID

    @property
    def duplicates(self) -> int:
        return self.received - self.counts.stored


class ReadingWriter(Protocol):
    async def store_and_enqueue(
        self,
        station_id: UUID,
        organization_id: UUID,
        readings: Sequence[ClassifiedReading],
        received_at: datetime,
        heartbeat: ClassifiedReading | None,
        correlation_id: UUID,
    ) -> StoreCounts:
        """In the current transaction: store the readings, enqueue the new `ok` ones with
        `correlation_id`, update the heartbeat with `heartbeat` (if any) and notify the
        evaluator."""
        ...


async def ingest_batch(
    station: AuthenticatedStation,
    readings: Sequence[Reading],
    clock: Clock,
    writer: ReadingWriter,
) -> IngestResult:
    received_at = clock.now()
    check_not_in_future(readings, received_at)
    classified = classify(readings, received_at)
    correlation_id = uuid7()
    counts = await writer.store_and_enqueue(
        station.station_id,
        station.organization_id,
        classified,
        received_at,
        heartbeat_reading(classified),
        correlation_id,
    )
    return IngestResult(received=len(readings), counts=counts, correlation_id=correlation_id)
