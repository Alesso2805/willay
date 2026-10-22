"""Viewing and confirming an alert from its email link or Telegram button.

- `preview_confirmation` (GET) only reads: opening the link never confirms, because email
  scanners open links on their own (SPEC).
- `confirm_alert` (POST) locks the alert so a concurrent second click sees the token used.
  From Telegram it also requires the clicker to be the recipient; the email link works
  for whoever holds it (SPEC).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from willay.alerts.domain.confirmation import ConfirmOutcome, token_problem
from willay.alerts.domain.delivery import hash_ack_token
from willay.alerts.domain.email import AlertMessage
from willay.incidents.application.lifecycle import (
    ContactActor,
    IncidentRepository,
    acknowledge_as_contact,
)
from willay.incidents.domain.lifecycle import IncidentStatus
from willay.shared.clock import Clock


@dataclass(frozen=True)
class AlertToConfirm:
    alert_id: UUID
    incident_id: UUID
    organization_id: UUID
    contact_id: UUID
    destination: str | None
    token_expires_at: datetime | None
    used_at: datetime | None  # when this alert was confirmed; None if never
    incident_status: IncidentStatus
    incident_acknowledged_at: datetime | None
    acknowledged_by: str | None  # name of the user or contact who acknowledged the incident
    message: AlertMessage


class ConfirmationRepository(Protocol):
    async def find(self, token_hash: str, *, lock: bool) -> AlertToConfirm | None:
        """The alert with this token hash; with `lock`, locked until the transaction ends."""
        ...

    async def mark_acknowledged(self, alert_id: UUID, now: datetime) -> None: ...


@dataclass(frozen=True)
class ConfirmationView:
    """What the page shows. `outcome` None: the token is valid and can be confirmed."""

    outcome: ConfirmOutcome | None
    alert: AlertToConfirm | None


async def preview_confirmation(
    token: str, *, confirmations: ConfirmationRepository, clock: Clock
) -> ConfirmationView:
    alert = await confirmations.find(hash_ack_token(token), lock=False)
    if alert is None:
        return ConfirmationView(ConfirmOutcome.UNKNOWN, None)
    problem = token_problem(alert.token_expires_at, alert.used_at, clock.now())
    if problem is not None:
        return ConfirmationView(problem, alert)
    if alert.incident_status is IncidentStatus.RESOLVED:
        return ConfirmationView(ConfirmOutcome.ALREADY_RESOLVED, alert)
    return ConfirmationView(None, alert)


async def confirm_alert(
    token: str,
    *,
    confirmations: ConfirmationRepository,
    incidents: IncidentRepository,
    clock: Clock,
    expected_destination: str | None = None,
) -> ConfirmationView:
    """With `expected_destination`, confirms only if the alert was sent there."""
    token_hash = hash_ack_token(token)
    alert = await confirmations.find(token_hash, lock=True)
    if alert is None:
        return ConfirmationView(ConfirmOutcome.UNKNOWN, None)
    if expected_destination is not None and alert.destination != expected_destination:
        # Without the alert: someone who did not receive it learns nothing about the incident.
        return ConfirmationView(ConfirmOutcome.NOT_YOURS, None)
    problem = token_problem(alert.token_expires_at, alert.used_at, clock.now())
    if problem is not None:
        return ConfirmationView(problem, alert)

    contact = ContactActor(alert.organization_id, alert.contact_id)
    previous = await acknowledge_as_contact(
        contact, alert.incident_id, incidents=incidents, clock=clock
    )
    if previous is IncidentStatus.RESOLVED:
        return ConfirmationView(ConfirmOutcome.ALREADY_RESOLVED, alert)
    await confirmations.mark_acknowledged(alert.alert_id, clock.now())

    # Re-read: the page shows who acknowledged the incident and when.
    fresh = await confirmations.find(token_hash, lock=False)
    confirmed = previous is IncidentStatus.OPEN
    outcome = ConfirmOutcome.CONFIRMED if confirmed else ConfirmOutcome.ALREADY_ACKNOWLEDGED
    return ConfirmationView(outcome, fresh or alert)
