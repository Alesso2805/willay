"""Simulated station signals: pure and reproducible from a seed.

Each step's value depends only on (seed, station, step): the noise comes from an RNG seeded
with that tuple, so step 37 is always the same regardless of how many stations run or in which
order, and tests can ask for any step.
"""

import math
import random
from dataclasses import dataclass
from enum import StrEnum

# Typical values per variable (Rímac dry-season discharge, level in metres, rain in mm).
BASELINES = {"discharge": 85.0, "water_level": 2.0, "rainfall": 0.5}
DEFAULT_BASELINE = 10.0
NOISE_SIGMA = 0.02  # relative Gaussian noise: typically ±2 %

DROP_FACTOR = 0.4  # after the drop discharge is at 40 %: 85 -> 34 m3/s, delta of 51
RISE_FACTOR = 2.0  # the rise doubles the value: level 2 m -> 4 m, above the 3.5 threshold
RISE_STEPS = 30  # the rise takes 30 steps (5 min at 10 s per step)

# SPEC demo scenario: river damming between Santa Eulalia and Chaclacayo.
RIMAC_DOWNSTREAM = "RIM-CHA-01"  # records the sudden discharge drop
RIMAC_UPSTREAM = "RIM-SEU-01"  # stops reporting 4 minutes later
RIMAC_SILENCE_DELAY_S = 240


class Behavior(StrEnum):
    NORMAL = "normal"
    RISE = "rise"
    DROP = "drop"
    SILENCE = "silence"


class Scenario(StrEnum):
    NORMAL = "normal"
    RISE = "rise"
    DROP = "drop"
    SILENCE = "silence"
    RIMAC = "rimac"


@dataclass(frozen=True)
class StationPlan:
    code: str
    variable: str
    behavior: Behavior
    event_step: int = 0  # step where the rise, drop or silence starts


class MissingStationsError(Exception):
    pass


def value_at(plan: StationPlan, seed: int, step: int) -> float | None:
    """Value at `step`, or None if the station is silent."""
    level = _level(plan, step)
    if level is None:
        return None
    base = BASELINES.get(plan.variable, DEFAULT_BASELINE)
    noise = random.Random(f"{seed}:{plan.code}:{step}").gauss(0.0, NOISE_SIGMA)
    return round(max(0.0, base * level * (1.0 + noise)), 3)


def _level(plan: StationPlan, step: int) -> float | None:
    elapsed = step - plan.event_step
    match plan.behavior:
        case Behavior.NORMAL:
            return 1.0
        case Behavior.SILENCE:
            return None if elapsed >= 0 else 1.0
        case Behavior.DROP:
            return DROP_FACTOR if elapsed >= 0 else 1.0
        case Behavior.RISE:
            progress = min(max(elapsed, 0), RISE_STEPS) / RISE_STEPS
            return 1.0 + (RISE_FACTOR - 1.0) * progress


def build_plan(
    scenario: Scenario,
    stations: list[tuple[str, str]],
    *,
    event_step: int,
    interval_s: float,
) -> list[StationPlan]:
    """`stations` are (code, variable) pairs. In the simple scenarios every station follows
    the same behavior; `rimac` reproduces the SPEC demo."""
    if scenario is not Scenario.RIMAC:
        behavior = Behavior(scenario.value)
        return [StationPlan(code, variable, behavior, event_step) for code, variable in stations]

    codes = {code for code, _ in stations}
    missing = {RIMAC_DOWNSTREAM, RIMAC_UPSTREAM} - codes
    if missing:
        raise MissingStationsError(f"the rimac scenario needs stations {sorted(missing)}")
    silence_step = event_step + math.ceil(RIMAC_SILENCE_DELAY_S / interval_s)
    special = {
        RIMAC_DOWNSTREAM: (Behavior.DROP, event_step),
        RIMAC_UPSTREAM: (Behavior.SILENCE, silence_step),
    }
    return [
        StationPlan(code, variable, *special.get(code, (Behavior.NORMAL, 0)))
        for code, variable in stations
    ]
