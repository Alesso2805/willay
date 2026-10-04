"""Alerts: who each escalation level notifies and through which channel (SPEC: Alerts).

A contact lacking the level's channel (no email, or Telegram not linked) gets a `skipped`
alert instead of none, so the timeline shows who could not be reached.
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class Channel(StrEnum):
    EMAIL = "email"
    TELEGRAM = "telegram"


class AlertStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"
    ACKNOWLEDGED = "acknowledged"


@dataclass(frozen=True)
class Target:
    """A contact that a level must notify through one channel."""

    contact_id: UUID
    channel: Channel
    destination: str | None  # email or Telegram chat_id; None if the contact has none

    @property
    def reachable(self) -> bool:
        return self.destination is not None and self.destination.strip() != ""

    @property
    def initial_status(self) -> AlertStatus:
        return AlertStatus.PENDING if self.reachable else AlertStatus.SKIPPED


class Reason(StrEnum):
    """Why an alert was skipped or a level expired, recorded in the timeline as a code with its
    parameters (VIG-40): the dashboard says it in each user's language. Events from before
    VIG-40 keep their Spanish text under `reason`."""

    NO_EMAIL = "no_email"
    NO_TELEGRAM = "no_telegram"
    # A pending alert of an incident that is no longer open is not sent (SPEC): nobody should
    # be asked to confirm something already handled.
    INCIDENT_ACKNOWLEDGED = "incident_acknowledged"
    INCIDENT_RESOLVED = "incident_resolved"
    NOT_ACKNOWLEDGED = "not_acknowledged"  # {wait_s}
    LEVEL_REACHED_NOBODY = "level_reached_nobody"  # {level}
    LEVEL_REMOVED = "level_removed"  # {level}


SKIP_REASON = {Channel.EMAIL: Reason.NO_EMAIL, Channel.TELEGRAM: Reason.NO_TELEGRAM}
