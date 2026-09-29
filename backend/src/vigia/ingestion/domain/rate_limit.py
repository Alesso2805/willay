"""Límite de 60 lotes por minuto y estación (SPEC: Rate limit).

Ventanas fijas de un minuto (hh:mm:00). Es la variante más simple y barata de contar en
Postgres; su límite conocido es que en el cambio de minuto caben hasta 120 lotes en
pocos segundos, aceptable para proteger la API de una estación desbocada.
"""

import math
from datetime import datetime, timedelta

MAX_BATCHES_PER_MINUTE = 60
WINDOW = timedelta(minutes=1)


class RateLimitExceededError(Exception):
    def __init__(self, retry_after_s: int) -> None:
        super().__init__(f"límite de {MAX_BATCHES_PER_MINUTE} lotes por minuto superado")
        self.retry_after_s = retry_after_s


def window_start(now: datetime) -> datetime:
    return now.replace(second=0, microsecond=0)


def seconds_until_next_window(now: datetime) -> int:
    remaining = (window_start(now) + WINDOW - now).total_seconds()
    return max(1, math.ceil(remaining))


def check_count(count: int, now: datetime) -> None:
    """`count` incluye el lote actual."""
    if count > MAX_BATCHES_PER_MINUTE:
        raise RateLimitExceededError(seconds_until_next_window(now))
