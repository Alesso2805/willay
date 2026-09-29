"""Regla de tasa de cambio (VIG-16): subida o caída mayor a delta dentro de T minutos.

`params` en core.rules: {"direction": "down", "delta": 40.0, "window_minutes": 10}.

La variación se mide del pico al valle de la ventana respetando el orden en el tiempo:
una caída es un valor alto seguido de uno más bajo; una subida, al revés. Así se detecta
también una caída brusca que se recupera en parte dentro de la ventana, que comparando
solo la primera y la última lectura pasaría inadvertida (85 → 34 → 60 m3/s: primera
contra última da 25; pico contra valle, 51).

La frontera es estricta, "mayor a delta" (SPEC): una caída de exactamente delta no dispara.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any

from vigia.rules.domain.errors import InvalidRuleParamsError

# La regla se evalúa con cada lectura y lee su ventana completa: a 10 s por lectura, una
# hora son 361 lecturas. Las variaciones lentas de varias horas no son "bruscas".
MAX_WINDOW_MINUTES = 60


class Direction(StrEnum):
    UP = "up"
    DOWN = "down"


@dataclass(frozen=True)
class RateOfChangeParams:
    direction: Direction
    delta: float
    window_minutes: int

    @property
    def window(self) -> timedelta:
        return timedelta(minutes=self.window_minutes)


@dataclass(frozen=True)
class Change:
    """Variación entre dos lecturas de la ventana: de la posición `start` a `end`."""

    start: int
    end: int
    amount: float  # siempre positivo, en la dirección de la regla


def parse_rate_of_change(raw: Mapping[str, Any]) -> RateOfChangeParams:
    try:
        direction = Direction(raw["direction"])
        delta = raw["delta"]
        window_minutes = raw["window_minutes"]
    except (KeyError, ValueError) as exc:
        raise InvalidRuleParamsError(f"parámetros de tasa de cambio inválidos: {raw}") from exc
    if not isinstance(delta, int | float) or isinstance(delta, bool) or not delta > 0:
        raise InvalidRuleParamsError("delta debe ser un número mayor que cero")
    if (
        not isinstance(window_minutes, int)
        or isinstance(window_minutes, bool)
        or not 1 <= window_minutes <= MAX_WINDOW_MINUTES
    ):
        raise InvalidRuleParamsError(
            f"window_minutes debe ser un entero entre 1 y {MAX_WINDOW_MINUTES}"
        )
    return RateOfChangeParams(direction, float(delta), window_minutes)


def detect_change(params: RateOfChangeParams, chronological: Sequence[float]) -> Change | None:
    """La mayor variación de la ventana en la dirección de la regla, si supera delta.

    `chronological`: los valores `ok` de la ventana, del más antiguo al más reciente.
    Una sola pasada: para cada lectura basta con el extremo (pico en una caída, valle en
    una subida) de las anteriores, no hace falta comparar todos los pares.
    """
    # Con el signo, una subida se calcula como una caída de los valores negados.
    sign = 1.0 if params.direction is Direction.DOWN else -1.0
    best: Change | None = None
    extreme = 0
    for end in range(1, len(chronological)):
        if sign * chronological[end - 1] > sign * chronological[extreme]:
            extreme = end - 1
        amount = sign * (chronological[extreme] - chronological[end])
        if amount > params.delta and (best is None or amount > best.amount):
            best = Change(extreme, end, amount)
    return best
