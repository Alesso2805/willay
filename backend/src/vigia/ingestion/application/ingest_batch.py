"""Caso de uso: guardar un lote de lecturas de una estación y encolarlas para evaluar."""

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
)
from vigia.shared.clock import Clock


@dataclass(frozen=True)
class StoreCounts:
    stored: int  # nuevas; el resto eran duplicados por (station_id, measured_at)
    late: int  # de las nuevas, cuántas llegaron tarde (guardadas, no encoladas)
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
    ) -> StoreCounts:
        """Guarda las lecturas, encola las nuevas con calidad ok y avisa al evaluador,
        todo en la transacción en curso."""
        ...


async def ingest_batch(
    station: AuthenticatedStation,
    readings: Sequence[Reading],
    clock: Clock,
    writer: ReadingWriter,
) -> IngestResult:
    received_at = clock.now()
    check_not_in_future(readings, received_at)
    counts = await writer.store_and_enqueue(
        station.station_id,
        station.organization_id,
        classify(readings, received_at),
        received_at,
    )
    return IngestResult(received=len(readings), counts=counts)
