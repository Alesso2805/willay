"""Confirming an alert with its token: single use, valid for 24 h.

Confirming any alert acknowledges the incident (SPEC). If someone else got there first, the
alert is recorded as seen without changing who acknowledged; if the incident is already
resolved, nothing changes. Neither case is an error for the person confirming.
"""

from datetime import datetime
from enum import StrEnum


class ConfirmOutcome(StrEnum):
    CONFIRMED = "confirmed"  # this contact acknowledged the incident
    ALREADY_ACKNOWLEDGED = "already_acknowledged"  # someone else was first; alert marked seen
    ALREADY_RESOLVED = "already_resolved"
    UNKNOWN = "unknown"  # no token matches
    EXPIRED = "expired"
    USED = "used"
    NOT_YOURS = "not_yours"  # the Telegram button was pressed by someone else


def token_problem(
    expires_at: datetime | None, used_at: datetime | None, now: datetime
) -> ConfirmOutcome | None:
    """Why the token is no longer valid, or None if it still is."""
    if used_at is not None:
        return ConfirmOutcome.USED
    if expires_at is None or now >= expires_at:
        return ConfirmOutcome.EXPIRED
    return None
