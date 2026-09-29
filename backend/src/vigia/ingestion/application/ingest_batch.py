"""Caso de uso: guardar un lote de lecturas de una estación y encolarlas para evaluar."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from vigia.ingestion.application.authenticate_station import AuthenticatedStation
from vigia.ingestion.domain.readings import Reading, check_not_in_future, in_measurement_order
from vigia.shared.clock import Clock


@dataclass(frozen=True)
class IngestResult:
    received: int
    stored: int  # nuevas; el resto eran duplicados por (station_id, measured_at)
    enqueued: int

    @property
    def duplicates(self) -> int:
        return self.received - self.stored


class ReadingWriter(Protocol):
    async def store_and_enqueue(
        self,
        station_id: UUID,
        organization_id: UUID,
        readings: Sequence[Reading],
        received_at: datetime,
    ) -> tuple[int, int]:
        """Guarda las lecturas y encola las nuevas de forma atómica. Devuelve (stored, enqueued)."""
        ...


async def ingest_batch(
    station: AuthenticatedStation,
    readings: Sequence[Reading],
    clock: Clock,
    writer: ReadingWriter,
) -> IngestResult:
    received_at = clock.now()
    check_not_in_future(readings, received_at)
    stored, enqueued = await writer.store_and_enqueue(
        station.station_id,
        station.organization_id,
        in_measurement_order(readings),
        received_at,
    )
    return IngestResult(received=len(readings), stored=stored, enqueued=enqueued)
