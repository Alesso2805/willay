"""Rate-of-change rule (VIG-16): a rise or drop greater than delta within T minutes.

`params` in core.rules: {"direction": "down", "delta": 40.0, "window_minutes": 10}.

The change is measured peak to trough in time order, so a sharp drop that partly recovers
within the window still fires (85 → 34 → 60 m3/s: 25 first-to-last, 51 peak-to-trough).
The boundary is strict, "greater than delta" (SPEC): a drop of exactly delta does not fire.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any

from vigia.rules.domain.errors import InvalidRuleParamsError

# The rule reads its whole window on every reading: at 10 s per reading an hour is 361
# readings. Slow changes over several hours are not "sharp" anyway.
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
    """Change between two readings of the window: from position `start` to `end`."""

    start: int
    end: int
    amount: float  # always positive, in the rule's direction


def parse_rate_of_change(raw: Mapping[str, Any]) -> RateOfChangeParams:
    try:
        direction = Direction(raw["direction"])
        delta = raw["delta"]
        window_minutes = raw["window_minutes"]
    except (KeyError, ValueError) as exc:
        raise InvalidRuleParamsError(f"invalid rate-of-change params: {raw}") from exc
    if not isinstance(delta, int | float) or isinstance(delta, bool) or not delta > 0:
        raise InvalidRuleParamsError("delta must be a number greater than zero")
    if (
        not isinstance(window_minutes, int)
        or isinstance(window_minutes, bool)
        or not 1 <= window_minutes <= MAX_WINDOW_MINUTES
    ):
        raise InvalidRuleParamsError(
            f"window_minutes must be an integer between 1 and {MAX_WINDOW_MINUTES}"
        )
    return RateOfChangeParams(direction, float(delta), window_minutes)


def detect_change(params: RateOfChangeParams, chronological: Sequence[float]) -> Change | None:
    """The largest change in the window in the rule's direction, if it exceeds delta.

    `chronological`: the window's `ok` values, oldest first. A single pass suffices: for each
    reading, track only the extreme of the previous ones (peak for a drop, trough for a rise).
    """
    # With the sign, a rise is computed as a drop of the negated values.
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
