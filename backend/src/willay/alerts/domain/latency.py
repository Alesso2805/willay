"""Reading received → first alert sent: the latency the MVP promises, p95 < 30 s.

Each incident opened by a reading contributes one value: from that reading's `received_at`
to the first of its alerts that was sent. Silence incidents do not count (no reading opens
them), nor incidents none of whose alerts went out.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

TARGET_P95_S = 30.0  # SPEC: success metric and latency NFR


@dataclass(frozen=True)
class LatencySummary:
    count: int
    p50: float
    p95: float
    max: float

    @property
    def meets_target(self) -> bool:
        return self.p95 < TARGET_P95_S


def percentile(sorted_values: Sequence[float], fraction: float) -> float:
    """Linear interpolation between the closest ranks, like Postgres' percentile_cont."""
    position = (len(sorted_values) - 1) * fraction
    lower, upper = math.floor(position), math.ceil(position)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def summarize(seconds: Sequence[float]) -> LatencySummary | None:
    """None without values: no incident sent an alert in the period."""
    if not seconds:
        return None
    ordered = sorted(seconds)
    return LatencySummary(
        count=len(ordered),
        p50=percentile(ordered, 0.5),
        p95=percentile(ordered, 0.95),
        max=ordered[-1],
    )
