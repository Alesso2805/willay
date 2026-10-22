"""Level-based escalation: when an incident moves up a level or exhausts its policy.

The current level expires when `wait_s` has passed since it was notified with no
acknowledgement; when it reached nobody (all alerts skipped, SPEC: escalate immediately),
including level 1 on opening; or when an admin removed it from the policy meanwhile.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from willay.alerts.domain.alerts import Reason


class Step(StrEnum):
    WAIT = "wait"
    ESCALATE = "escalate"
    EXHAUST = "exhaust"


@dataclass(frozen=True)
class Decision:
    step: Step
    reason: Reason | None = None  # why the level expired; stored in the timeline event
    reason_params: Mapping[str, int] = field(default_factory=dict)

    def payload(self) -> dict[str, object]:
        """How the timeline event records the reason."""
        return {"reason_code": self.reason, "reason_params": dict(self.reason_params)}


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
    reason: Reason
    params: dict[str, int]
    if state.wait_s is None:
        reason, params = Reason.LEVEL_REMOVED, {"level": level}
    elif state.nobody_alerted:
        reason, params = Reason.LEVEL_REACHED_NOBODY, {"level": level}
    elif now - state.level_started_at >= timedelta(seconds=state.wait_s):
        reason, params = Reason.NOT_ACKNOWLEDGED, {"wait_s": state.wait_s}
    else:
        return Decision(Step.WAIT)
    step = Step.ESCALATE if state.next_level is not None else Step.EXHAUST
    return Decision(step, reason, params)
