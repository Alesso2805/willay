"""Level-based escalation (VIG-24): when an incident moves up a level or exhausts its policy.

The current level expires when `wait_s` has passed since it was notified with no
acknowledgement; when it reached nobody (all alerts skipped, SPEC: escalate immediately),
including level 1 on opening; or when an admin removed it from the policy meanwhile.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class Step(StrEnum):
    WAIT = "wait"
    ESCALATE = "escalate"
    EXHAUST = "exhaust"


@dataclass(frozen=True)
class Decision:
    step: Step
    reason: str | None = None  # why the level expired; stored in the timeline event


@dataclass(frozen=True)
class LevelState:
    """The current level of an open incident, checked against the current policy."""

    current_level: int
    level_started_at: datetime
    wait_s: int | None  # None: the level no longer exists in the policy
    next_level: int | None
    nobody_alerted: bool  # every alert of the level was skipped


def decide(state: LevelState, now: datetime) -> Decision:
    level = state.current_level
    if state.wait_s is None:
        reason = f"el nivel {level} ya no existe en la política"
    elif state.nobody_alerted:
        reason = f"el nivel {level} no pudo avisar a nadie"
    elif now - state.level_started_at >= timedelta(seconds=state.wait_s):
        reason = f"nadie confirmó en {state.wait_s} s"
    else:
        return Decision(Step.WAIT)
    step = Step.ESCALATE if state.next_level is not None else Step.EXHAUST
    return Decision(step, reason)
