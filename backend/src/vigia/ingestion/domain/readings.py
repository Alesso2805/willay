"""Lecturas de una estación: reglas del lote que no dependen de HTTP ni de SQL."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

MAX_BATCH_SIZE = 500
# Tolerancia al desfase del reloj de la estación. Más allá, una lectura "del futuro" es un
# reloj mal configurado: aceptarla abriría ventanas de reglas con datos imposibles.
MAX_CLOCK_SKEW = timedelta(minutes=5)
# Una lectura que llega más de 1 h después de medirse ya no sirve para alertar a tiempo:
# se guarda para el historial, pero no se evalúa ni cuenta como latido (SPEC).
LATE_AFTER = timedelta(hours=1)


class Quality(StrEnum):
    OK = "ok"
    LATE = "late"


@dataclass(frozen=True)
class Reading:
    measured_at: datetime
    value: float


@dataclass(frozen=True)
class ClassifiedReading:
    measured_at: datetime
    value: float
    quality: Quality


class FutureReadingsError(Exception):
    def __init__(self, indices: list[int]) -> None:
        super().__init__(f"lecturas con measured_at en el futuro: {indices}")
        self.indices = indices


def check_not_in_future(readings: Sequence[Reading], now: datetime) -> None:
    limit = now + MAX_CLOCK_SKEW
    late = [i for i, reading in enumerate(readings) if reading.measured_at > limit]
    if late:
        raise FutureReadingsError(late)


def quality_of(measured_at: datetime, received_at: datetime) -> Quality:
    return Quality.LATE if received_at - measured_at > LATE_AFTER else Quality.OK


def classify(readings: Sequence[Reading], received_at: datetime) -> list[ClassifiedReading]:
    """Ordena por measured_at (las estaciones pueden enviar el lote desordenado) y
    marca la calidad de cada lectura según cuánto tardó en llegar."""
    ordered = sorted(readings, key=lambda reading: reading.measured_at)
    return [
        ClassifiedReading(r.measured_at, r.value, quality_of(r.measured_at, received_at))
        for r in ordered
    ]
