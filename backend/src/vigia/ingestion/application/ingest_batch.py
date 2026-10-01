"""Use case: store a station's batch of readings and enqueue them for evaluation."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from vigia.ingestion.application.authenticate_station import AuthenticatedStation
from vigia.ingestion.domain.readings import (
    ClassifiedReading,
    Reading,
    check_not_in_future,
    classify,
    heartbeat_reading,
)
from vigia.shared.clock import Clock


@dataclass(frozen=True)
class StoreCounts:
    stored: int  # new ones; the rest were duplicates by (station_id, measured_at)
    late: int  # of the new ones, how many were late (stored, not enqueued)
    enqueued: int


@dataclass(frozen=True)
class IngestResult:
    received: int
    counts: StoreCounts

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
    ) -> StoreCounts:
        """In the current transaction: store the readings, enqueue the new `ok` ones,
        update the heartbeat with `heartbeat` (if any) and notify the evaluator."""
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
    counts = await writer.store_and_enqueue(
        station.station_id,
        station.organization_id,
        classified,
        received_at,
        heartbeat_reading(classified),
    )
    return IngestResult(received=len(readings), counts=counts)
