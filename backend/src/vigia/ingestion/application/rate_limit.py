"""Caso de uso: contar el lote en la ventana del minuto y rechazarlo si supera el límite."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from vigia.ingestion.domain.rate_limit import check_count, window_start
from vigia.shared.clock import Clock


class BatchCounter(Protocol):
    async def hit(self, station_id: UUID, window: datetime) -> int:
        """Suma 1 al contador de la ventana y devuelve el total, de forma atómica."""
        ...


async def enforce_rate_limit(station_id: UUID, clock: Clock, counter: BatchCounter) -> None:
    now = clock.now()
    count = await counter.hit(station_id, window_start(now))
    check_count(count, now)
