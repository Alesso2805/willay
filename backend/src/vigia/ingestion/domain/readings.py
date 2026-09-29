"""Lecturas de una estación: reglas del lote que no dependen de HTTP ni de SQL."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

MAX_BATCH_SIZE = 500
# Tolerancia al desfase del reloj de la estación. Más allá, una lectura "del futuro" es un
# reloj mal configurado: aceptarla abriría ventanas de reglas con datos imposibles.
MAX_CLOCK_SKEW = timedelta(minutes=5)


@dataclass(frozen=True)
class Reading:
    measured_at: datetime
    value: float


class FutureReadingsError(Exception):
    def __init__(self, indices: list[int]) -> None:
        super().__init__(f"lecturas con measured_at en el futuro: {indices}")
        self.indices = indices


def check_not_in_future(readings: Sequence[Reading], now: datetime) -> None:
    limit = now + MAX_CLOCK_SKEW
    late = [i for i, reading in enumerate(readings) if reading.measured_at > limit]
    if late:
        raise FutureReadingsError(late)


def in_measurement_order(readings: Sequence[Reading]) -> list[Reading]:
    """Las estaciones pueden enviar el lote desordenado; se procesa por measured_at."""
    return sorted(readings, key=lambda reading: reading.measured_at)
