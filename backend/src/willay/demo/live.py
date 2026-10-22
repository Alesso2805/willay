"""The public demo's live side: what the demo worker plays, and when. Pure.

Every demo station reports every 10 s with the simulator's own signals, so the map is never
empty. A scenario run plays SPEC's Rímac story from its own start:
- one minute of normal river;
- the downstream station's sudden discharge drop;
- the upstream station going silent four minutes later;
- four more minutes of silence, so its incident opens and climbs a level before the station
  comes back and the run ends.

The worker also restores the demo organization every night at a local hour.
"""

import math
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from willay.ingestion.domain.simulation import (
    RIMAC_SILENCE_DELAY_S,
    Behavior,
    Scenario,
    StationPlan,
    build_plan,
    value_at,
)

INTERVAL_S = 10  # the seed stations' expected interval
SIGNAL_SEED = 42  # the same signals as `make demo`
EVENT_STEP = 6  # one minute of normal river before the drop
SILENCE_STEP = EVENT_STEP + math.ceil(RIMAC_SILENCE_DELAY_S / INTERVAL_S)
END_STEP = SILENCE_STEP + 24  # four minutes of silence: the incident opens and escalates once
DURATION_S = END_STEP * INTERVAL_S


class Phase(StrEnum):
    NORMAL = "normal"  # the river as usual
    DROP = "drop"  # the downstream discharge fell: a rate-of-change incident opens
    SILENCE = "silence"  # the upstream station stopped reporting: a silence incident opens
    DONE = "done"  # the stations report again


TIMELINE: tuple[tuple[Phase, int], ...] = (
    (Phase.NORMAL, 0),
    (Phase.DROP, EVENT_STEP * INTERVAL_S),
    (Phase.SILENCE, SILENCE_STEP * INTERVAL_S),
    (Phase.DONE, DURATION_S),
)


def phase_at(elapsed_s: float) -> Phase:
    """Where the story is, `elapsed_s` after the run started."""
    current = Phase.NORMAL
    for phase, at_s in TIMELINE:
        if elapsed_s >= at_s:
            current = phase
    return current


def scenario_step(started_at: datetime, now: datetime) -> int:
    """The run's step at `now`: step 0 is its start, one step every 10 s."""
    return max(0, math.floor((now - started_at).total_seconds() / INTERVAL_S))


def scenario_plans(stations: list[tuple[str, str]]) -> list[StationPlan]:
    """`stations` are the demo's active (code, variable) pairs. Raises MissingStationsError if
    a visitor deactivated one of the two stations the story needs."""
    return build_plan(Scenario.RIMAC, stations, event_step=EVENT_STEP, interval_s=INTERVAL_S)


def normal_plans(stations: list[tuple[str, str]]) -> list[StationPlan]:
    return [StationPlan(code, variable, Behavior.NORMAL) for code, variable in stations]


def normal_step(now: datetime) -> int:
    """Outside a run, steps are counted from the epoch, so every 10 s boundary is one reading
    and a restarted worker neither repeats nor skips one."""
    return math.floor(now.timestamp() / INTERVAL_S)


def normal_time(step: int) -> datetime:
    return datetime.fromtimestamp(step * INTERVAL_S, UTC)


def scenario_time(started_at: datetime, step: int) -> datetime:
    return started_at + timedelta(seconds=step * INTERVAL_S)


def values(plans: list[StationPlan], step: int) -> dict[str, float | None]:
    """Each station's value at `step`; None while it is silent."""
    return {plan.code: value_at(plan, SIGNAL_SEED, step) for plan in plans}


def next_restore(after: datetime, timezone: str, hour: int) -> datetime:
    """The first `hour`:00 in `timezone` strictly after `after`."""
    zone = ZoneInfo(timezone)
    local = after.astimezone(zone)
    candidate = _at(local.date(), hour, zone)
    if candidate <= after:
        candidate = _at(local.date() + timedelta(days=1), hour, zone)
    return candidate


def _at(day: date, hour: int, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=zone).astimezone(UTC)
