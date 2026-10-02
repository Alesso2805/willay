"""Rule preview (VIG-27): when a draft rule would have opened an incident over past readings.

It replays the readings in order with the evaluator's own functions and marks the start of
each episode: the first reading at which the rule fires after one at which it did not. While
it keeps firing, the real evaluator would add to the incident already open, not open another,
so those readings are not marked. Cooldown is not simulated: it depends on when someone
resolves the incident, which a preview cannot know.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from willay.rules.domain.rate_of_change import RateOfChangeParams, detect_change
from willay.rules.domain.silence import is_silent
from willay.rules.domain.threshold import ThresholdParams


@dataclass(frozen=True)
class Point:
    at: datetime
    value: float


@dataclass(frozen=True)
class Firing:
    at: datetime
    value: float | None  # None for silence: what fires is the absence of a reading


def threshold_firings(
    params: ThresholdParams, readings: Sequence[Point], since: datetime
) -> list[Firing]:
    """`readings`: oldest first, possibly starting before `since` so that the first ones of
    the period count their predecessors."""
    firings: list[Firing] = []
    run = 0
    for reading in readings:
        run = run + 1 if params.breached_by(reading.value) else 0
        # Exactly N: the run just reached the rule's length, so this reading opens the episode.
        if run == params.consecutive and reading.at >= since:
            firings.append(Firing(reading.at, reading.value))
    return firings


def rate_of_change_firings(
    params: RateOfChangeParams, readings: Sequence[Point], since: datetime
) -> list[Firing]:
    """Each reading is evaluated with its window [t - T, t], as the evaluator does on arrival."""
    firings: list[Firing] = []
    start = 0
    firing = False
    for end, reading in enumerate(readings):
        while readings[start].at < reading.at - params.window:
            start += 1
        window = [r.value for r in readings[start : end + 1]]
        fires = detect_change(params, window) is not None
        if fires and not firing and reading.at >= since:
            firings.append(Firing(reading.at, reading.value))
        firing = fires
    return firings


def silence_firings(
    threshold: timedelta,
    received: Sequence[datetime],
    since: datetime,
    until: datetime,
) -> list[Firing]:
    """`received`: when the station reported, oldest first, including its last report before
    `since` if any. A gap fires once it reaches the threshold; a station that never reported
    is not silent (SPEC)."""
    firings: list[Firing] = []
    for i, current in enumerate(received):
        following = received[i + 1] if i + 1 < len(received) else None
        opens_at = current + threshold
        closes_at = following if following is not None else until
        # Silent from opens_at while no report came; it fires if that moment is in the period.
        if is_silent(current, threshold, closes_at) and since <= opens_at <= until:
            firings.append(Firing(opens_at, None))
    return firings
