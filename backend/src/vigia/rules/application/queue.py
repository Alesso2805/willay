"""Interfaz de la cola de evaluación (ADR-0002).

El evaluador no sabe que la cola vive en Postgres: si algún día hace falta Redis Streams
o Kafka, se cambia la implementación, no el dominio ni el bucle del worker.

Garantías que toda implementación debe dar:
- `claim` confirma en su propia transacción el intento (attempts + 1) y el visibility
  timeout ANTES de evaluar: si el worker muere, el contador sobrevive y la fila vuelve
  a estar disponible al vencer el timeout.
- `complete` va dentro de la transacción de la evaluación: sus escrituras (incidentes,
  alertas, evaluated_at) y la salida de la fila de la cola se confirman juntas.
- A los MAX_ATTEMPTS intentos la fila se marca como fallida y deja de bloquear la cola.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

VISIBILITY_TIMEOUT = timedelta(seconds=60)
MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class QueuedReading:
    queue_id: int
    station_id: UUID
    organization_id: UUID
    measured_at: datetime
    attempt: int  # número de este intento, 1..MAX_ATTEMPTS


class LostClaimError(Exception):
    """El visibility timeout venció y otro worker retomó la fila: esta evaluación se
    descarta (rollback) para no escribir dos veces."""


class EvaluationQueue(Protocol):
    async def claim(self, limit: int) -> list[QueuedReading]:
        """Toma hasta `limit` filas disponibles, en su propia transacción corta."""
        ...

    async def complete(self, tx: AsyncConnection, item: QueuedReading) -> None:
        """Marca la lectura como evaluada y la saca de la cola, dentro de `tx` (la
        transacción de la evaluación). Lanza LostClaimError si la fila ya no es nuestra."""
        ...

    async def fail(self, item: QueuedReading, error: str) -> bool:
        """Registra el error en su propia transacción. Devuelve True si la fila quedó
        marcada como fallida definitiva (último intento)."""
        ...
