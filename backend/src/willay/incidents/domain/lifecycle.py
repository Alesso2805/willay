"""Incident lifecycle: open → acknowledged → resolved.

Acknowledge only from `open` (it stops escalation). Resolve from `open` or `acknowledged`, as
resolved or false alarm; resolving without acknowledging first is a product decision so an
obvious false alarm closes in one step. `resolved` is final (the API answers 409).
"""

from enum import StrEnum


class IncidentStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class Resolution(StrEnum):
    RESOLVED = "resolved"
    FALSE_ALARM = "false_alarm"


class Transition(StrEnum):
    ACKNOWLEDGE = "acknowledge"
    RESOLVE = "resolve"


ALLOWED_FROM: dict[Transition, frozenset[IncidentStatus]] = {
    Transition.ACKNOWLEDGE: frozenset({IncidentStatus.OPEN}),
    Transition.RESOLVE: frozenset({IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED}),
}


class InvalidTransitionError(Exception):
    def __init__(self, transition: Transition, current: IncidentStatus) -> None:
        super().__init__(f"cannot {transition} an incident in status {current}")
        self.transition = transition
        self.current = current


def ensure_allowed(transition: Transition, current: IncidentStatus) -> None:
    if current not in ALLOWED_FROM[transition]:
        raise InvalidTransitionError(transition, current)
