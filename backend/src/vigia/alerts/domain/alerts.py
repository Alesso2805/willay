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


# A pending alert of an incident that is no longer open is not sent (SPEC): nobody should
# be asked to confirm something already handled. Reasons are stored in the timeline.
SKIP_ACKNOWLEDGED = "el incidente ya fue confirmado"
SKIP_RESOLVED = "el incidente ya fue resuelto"

SKIP_REASON = {
    Channel.EMAIL: "el contacto no tiene correo",
    Channel.TELEGRAM: "el contacto no vinculó Telegram",
}
