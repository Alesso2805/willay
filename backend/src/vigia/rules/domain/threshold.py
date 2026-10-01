"""Threshold rule (VIG-15): value out of bounds for N consecutive `ok` readings.

`params` in core.rules: {"operator": "gt", "value": 3.5, "consecutive": 2}.

The boundary is exact per operator: with gt 3.5 a reading of 3.5 is NOT out of bounds;
with ge it is.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from vigia.rules.domain.errors import InvalidRuleParamsError

# More than 60 readings in a row (10 min at 10 s per reading) is no longer "consecutive":
# it would be an average rule, which is a different type.
MAX_CONSECUTIVE = 60


class Operator(StrEnum):
    GT = "gt"
    GE = "ge"
    LT = "lt"
    LE = "le"


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
        raise InvalidRuleParamsError(f"invalid threshold params: {raw}") from exc
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise InvalidRuleParamsError("value must be a number")
    if (
        not isinstance(consecutive, int)
        or isinstance(consecutive, bool)  # bool is a subclass of int: True would pass as 1
        or not 1 <= consecutive <= MAX_CONSECUTIVE
    ):
        raise InvalidRuleParamsError(
            f"consecutive must be an integer between 1 and {MAX_CONSECUTIVE}"
        )
    return ThresholdParams(operator, float(value), consecutive)


def fires(params: ThresholdParams, latest_first: Sequence[float]) -> bool:
    """`latest_first`: the station's most recent `ok` values, latest first.

    Fires only if there are at least N readings and the N most recent are out of bounds.
    """
    window = latest_first[: params.consecutive]
    return len(window) == params.consecutive and all(params.breached_by(v) for v in window)
