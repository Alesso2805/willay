"""Reloj inyectable.

Todo el dominio y los workers reciben un `Clock` en lugar de llamar a `datetime.now()`.
Así los tests del detector de silencio y del escalamiento avanzan el tiempo con
`FakeClock` sin esperas reales. Ruff (TID251) prohíbe `datetime.now()` fuera de este archivo.
"""

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Instante actual, siempre con zona horaria UTC."""
        ...


class SystemClock:
    """Implementación real: la única que consulta el reloj del sistema."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    """Reloj controlado para tests: solo avanza cuando se le pide."""

    def __init__(self, start: datetime) -> None:
        self._now = _require_aware(start)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        if delta < timedelta(0):
            raise ValueError("FakeClock no retrocede; usa set() si lo necesitas")
        self._now += delta

    def set(self, instant: datetime) -> None:
        self._now = _require_aware(instant)


def _require_aware(instant: datetime) -> datetime:
    # Un datetime sin zona compararía mal con los timestamptz de Postgres.
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("El reloj solo acepta datetimes con zona horaria")
    return instant.astimezone(UTC)
