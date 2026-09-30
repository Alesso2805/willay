"""Ver y confirmar una alerta desde su enlace (VIG-23) o desde el botón de Telegram
(VIG-22): el token es el mismo.

- `preview_confirmation` (GET) solo lee: abrir el enlace nunca confirma, porque los
  escáneres de correo abren los enlaces solos (SPEC).
- `confirm_alert` (POST) bloquea la alerta: si llegan dos clics a la vez, el segundo ve
  el token ya usado. Desde Telegram exige además que quien pulsa sea el destinatario:
  el enlace del correo vale para quien lo tenga (SPEC), el botón solo en su chat.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from vigia.alerts.domain.confirmation import ConfirmOutcome, token_problem
from vigia.alerts.domain.delivery import hash_ack_token
from vigia.alerts.domain.email import AlertMessage
from vigia.incidents.application.lifecycle import (
    ContactActor,
    IncidentRepository,
    acknowledge_as_contact,
)
from vigia.incidents.domain.lifecycle import IncidentStatus
from vigia.shared.clock import Clock


@dataclass(frozen=True)
class AlertToConfirm:
    alert_id: UUID
    incident_id: UUID
    organization_id: UUID
    contact_id: UUID
    destination: str | None
    token_expires_at: datetime | None
    used_at: datetime | None  # cuándo se confirmó esta alerta; None si nunca
    incident_status: IncidentStatus
    incident_acknowledged_at: datetime | None
    acknowledged_by: str | None  # nombre del usuario o contacto que confirmó el incidente
    message: AlertMessage


class ConfirmationRepository(Protocol):
    async def find(self, token_hash: str, *, lock: bool) -> AlertToConfirm | None:
        """La alerta cuyo token tiene ese hash; con `lock`, bloqueada hasta el final."""
        ...

    async def mark_acknowledged(self, alert_id: UUID, now: datetime) -> None: ...


@dataclass(frozen=True)
class ConfirmationView:
    """Lo que la página muestra. `outcome` None: el token vale y se puede confirmar."""

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
    """Con `expected_destination`, solo confirma si la alerta se envió ahí."""
    token_hash = hash_ack_token(token)
    alert = await confirmations.find(token_hash, lock=True)
    if alert is None:
        return ConfirmationView(ConfirmOutcome.UNKNOWN, None)
    if expected_destination is not None and alert.destination != expected_destination:
        # Sin la alerta: a quien no la recibió no se le cuenta nada del incidente.
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

    # Releer: la página dice quién confirmó el incidente y cuándo.
    fresh = await confirmations.find(token_hash, lock=False)
    confirmed = previous is IncidentStatus.OPEN
    outcome = ConfirmOutcome.CONFIRMED if confirmed else ConfirmOutcome.ALREADY_ACKNOWLEDGED
    return ConfirmationView(outcome, fresh or alert)
