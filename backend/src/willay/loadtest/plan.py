"""What the load test sends and how it is judged, with no I/O.

Every station sends a normal series around 2 m and, once, a spike above its threshold rule,
at a moment spread over the run. Each spike opens one incident whose first alert gives one
sample of the latency SPEC promises (p95 < 30 s). The rest exercise ingestion and evaluation.
"""

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from willay.alerts.domain.latency import TARGET_P95_S, summarize

BASELINE_M = 2.0
THRESHOLD_M = 10.0  # each station's rule: value > 10 m once
SPIKE_M = 12.0
SETTLE_S = 120  # SPEC: no `ok` reading left unevaluated 120 s after it was received


@dataclass(frozen=True)
class LoadPlan:
    stations: int
    ticks: int  # rounds: every station sends one reading per tick
    interval_s: float
    spike_tick: tuple[int, ...]  # per station, the tick of its only spike

    def value(self, station: int, tick: int) -> float:
        if tick == self.spike_tick[station]:
            return SPIKE_M
        # A slow wave, different per station: plausible levels well under the threshold.
        return round(BASELINE_M + 0.5 * math.sin(tick / 6 + station), 3)


def build_plan(stations: int, minutes: float, interval_s: float, seed: int) -> LoadPlan:
    ticks = max(1, int(minutes * 60 / interval_s))
    rng = random.Random(seed)
    return LoadPlan(
        stations=stations,
        ticks=ticks,
        interval_s=interval_s,
        spike_tick=tuple(rng.randrange(ticks) for _ in range(stations)),
    )


@dataclass(frozen=True)
class Outcome:
    sent: int
    rejected: int  # answers other than 202
    unevaluated: int  # `ok` readings still without evaluated_at after SETTLE_S
    latencies: Sequence[float]  # received → first alert sent, one per incident

    def problems(self) -> list[str]:
        """Why the run fails SPEC; empty if it passes."""
        problems = []
        if self.rejected:
            problems.append(f"{self.rejected} of {self.sent} batches were not accepted")
        if self.unevaluated:
            problems.append(f"{self.unevaluated} readings were not evaluated within {SETTLE_S} s")
        summary = summarize(self.latencies)
        if summary is None:
            problems.append("no incident sent an alert: there is no latency to measure")
        elif not summary.meets_target:
            problems.append(f"p95 {summary.p95:.3f} s misses the target < {TARGET_P95_S:.0f} s")
        return problems
