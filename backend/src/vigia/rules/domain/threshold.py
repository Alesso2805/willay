"""Regla de umbral (VIG-15): valor fuera de límite durante N lecturas consecutivas `ok`.

`params` en core.rules: {"operator": "gt", "value": 3.5, "consecutive": 2}.

"Fuera de límite" depende del operador: gt (>), ge (>=), lt (<), le (<=). La frontera es
exacta: con gt 3.5, una lectura de 3.5 NO está fuera de límite; con ge, sí.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# Más de 60 lecturas seguidas (10 min a 10 s por lectura) ya no es "consecutivas": es
# una regla de promedio, que no es este tipo.
MAX_CONSECUTIVE = 60


class Operator(StrEnum):
    GT = "gt"
    GE = "ge"
    LT = "lt"
    LE = "le"


class InvalidRuleParamsError(Exception):
    pass


@dataclass(frozen=True)
class ThresholdParams:
    operator: Operator
    value: float
    consecutive: int

    def breached_by(self, reading: float) -> bool:
        match self.operator:
            case Operator.GT:
                return reading > self.value
            case Operator.GE:
                return reading >= self.value
            case Operator.LT:
                return reading < self.value
            case Operator.LE:
                return reading <= self.value


def parse_threshold(raw: Mapping[str, Any]) -> ThresholdParams:
    try:
        operator = Operator(raw["operator"])
        value = raw["value"]
        consecutive = raw["consecutive"]
    except (KeyError, ValueError) as exc:
        raise InvalidRuleParamsError(f"parámetros de umbral inválidos: {raw}") from exc
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise InvalidRuleParamsError("value debe ser un número")
    if not isinstance(consecutive, int) or not 1 <= consecutive <= MAX_CONSECUTIVE:
        raise InvalidRuleParamsError(f"consecutive debe ser un entero entre 1 y {MAX_CONSECUTIVE}")
    return ThresholdParams(operator, float(value), consecutive)


def fires(params: ThresholdParams, latest_first: Sequence[float]) -> bool:
    """`latest_first`: los valores `ok` más recientes de la estación, el último primero.

    Dispara solo si hay al menos N lecturas y las N más recientes están fuera de límite.
    """
    window = latest_first[: params.consecutive]
    return len(window) == params.consecutive and all(params.breached_by(v) for v in window)
