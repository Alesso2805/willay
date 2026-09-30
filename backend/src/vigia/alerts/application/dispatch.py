"""Enviar las alertas pendientes por correo (VIG-20) y Telegram (VIG-22), con el mismo patrón.

Como la cola de lecturas (ADR-0002), cada alerta pasa por transacciones cortas:
1. reclamo: SKIP LOCKED, `attempts + 1` y visibility timeout de 60 s, así otro dispatcher
   no la toma mientras se envía y, si este muere, se reintenta al vencer;
2. token: se guarda el hash del token de confirmación ANTES de enviar, para que el enlace
   del correo siempre funcione;
3. envío por el canal, fuera de toda transacción (un SMTP lento no retiene conexiones);
4. resultado: `sent`, reintento con espera exponencial, o `failed` al agotar los intentos,
   con su evento en la línea de tiempo del incidente.

Los pasos 2 a 4 exigen que el reclamo siga siendo suyo (`attempts` no cambió). Los envíos
de un lote van en paralelo: con un SMTP lento, en serie podrían superar el visibility
timeout y otro dispatcher reclamaría alertas que aún se están enviando.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

import structlog

from vigia.alerts.application.telegram_bot import TelegramError
from vigia.alerts.domain.alerts import Channel
from vigia.alerts.domain.delivery import AckToken, new_ack_token, retry_at
from vigia.alerts.domain.email import AlertMessage, EmailContent, compose_email
from vigia.alerts.domain.telegram import compose_alert_text
from vigia.shared.clock import Clock

log = structlog.get_logger()

VISIBILITY_TIMEOUT = timedelta(seconds=60)


@dataclass(frozen=True)
class ClaimedAlert:
    alert_id: UUID
    incident_id: UUID
    organization_id: UUID
    contact_id: UUID
    level_order: int
    attempt: int
    destination: str
    message: AlertMessage
    channel: Channel = Channel.EMAIL


class DeliveryError(Exception):
    """El canal no entregó el mensaje. El texto no debe incluir el destino (dato personal)."""


class DispatchQueue(Protocol):
    async def claim(
        self, channel: Channel, now: datetime, visible_again_at: datetime, limit: int
    ) -> list[ClaimedAlert]:
        """Reclama alertas pendientes y vencidas de incidentes abiertos. Antes omite las
        pendientes de incidentes ya confirmados o resueltos y da por fallidas las que
        agotaron sus intentos sin resultado (el worker murió a mitad de un envío)."""
        ...

    async def attach_token(self, alert: ClaimedAlert, token: AckToken) -> bool:
        """Guarda el hash del token. False si el reclamo ya no es suyo."""
        ...

    async def sent(self, alert: ClaimedAlert, now: datetime) -> None: ...

    async def failed(
        self, alert: ClaimedAlert, error: str, retry: datetime | None, now: datetime
    ) -> None:
        """Reintento en `retry`, o `failed` definitivo si es None."""
        ...


class EmailSender(Protocol):
    async def send(self, to: str, content: EmailContent) -> None:
        """Lanza DeliveryError si el servidor no aceptó el mensaje."""
        ...


@dataclass(frozen=True)
class DispatchResult:
    claimed: int
    sent: int
    failed: int


class DeliveryChannel(Protocol):
    """Cómo se entrega una alerta por un canal: arma su mensaje y lo envía."""

    @property
    def channel(self) -> Channel: ...

    async def deliver(self, destination: str, message: AlertMessage, token: str) -> None:
        """Lanza DeliveryError si el canal no la aceptó."""
        ...


class EmailChannel:
    """Correo con el enlace a la página de confirmación (VIG-20, VIG-23)."""

    channel = Channel.EMAIL

    def __init__(self, sender: EmailSender, confirm_base_url: str) -> None:
        self._sender = sender
        self._confirm_base_url = confirm_base_url.rstrip("/")

    async def deliver(self, destination: str, message: AlertMessage, token: str) -> None:
        confirm_url = f"{self._confirm_base_url}/confirmar/{token}"
        await self._sender.send(destination, compose_email(message, confirm_url))


class TelegramSender(Protocol):
    async def send_alert(self, chat_id: int, text: str, callback_data: str) -> None:
        """Lanza TelegramError si Telegram no aceptó el mensaje."""
        ...


class TelegramChannel:
    """Mensaje de Telegram con un botón cuyo `callback_data` es el token (VIG-22): 43
    caracteres, dentro de los 64 que admite Telegram."""

    channel = Channel.TELEGRAM

    def __init__(self, api: TelegramSender) -> None:
        self._api = api

    async def deliver(self, destination: str, message: AlertMessage, token: str) -> None:
        try:
            await self._api.send_alert(int(destination), compose_alert_text(message), token)
        except TelegramError as exc:
            raise DeliveryError(str(exc)) from None


class AlertDispatcher:
    def __init__(self, queue: DispatchQueue, channel: DeliveryChannel, clock: Clock) -> None:
        self._queue = queue
        self._channel = channel
        self._clock = clock

    async def dispatch(self, limit: int) -> DispatchResult:
        now = self._clock.now()
        claimed = await self._queue.claim(
            self._channel.channel, now, now + VISIBILITY_TIMEOUT, limit
        )
        outcomes = await asyncio.gather(
            *(self._deliver(alert) for alert in claimed), return_exceptions=True
        )
        for alert, outcome in zip(claimed, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                # Un error inesperado no pierde la alerta: se reintenta al vencer el reclamo.
                log.error("alert_dispatch_crashed", alert_id=str(alert.alert_id), exc_info=outcome)
        return DispatchResult(
            claimed=len(claimed),
            sent=sum(1 for o in outcomes if o is True),
            failed=sum(1 for o in outcomes if o is False),
        )

    async def _deliver(self, alert: ClaimedAlert) -> bool | None:
        """True si se envió, False si falló, None si el reclamo ya no era suyo."""
        token = new_ack_token(self._clock.now())
        if not await self._queue.attach_token(alert, token):
            return None
        bound = log.bind(
            alert_id=str(alert.alert_id), attempt=alert.attempt, channel=alert.channel.value
        )
        try:
            await self._channel.deliver(alert.destination, alert.message, token.token)
        except DeliveryError as exc:
            now = self._clock.now()
            retry = retry_at(alert.attempt, now)
            await self._queue.failed(alert, str(exc), retry, now)
            bound.warning("alert_send_failed", error=str(exc), final=retry is None)
            return False
        await self._queue.sent(alert, self._clock.now())
        bound.info("alert_sent", incident_id=str(alert.incident_id))
        return True


class EmailDispatcher(AlertDispatcher):
    """Atajo del dispatcher de correo."""

    def __init__(
        self, queue: DispatchQueue, sender: EmailSender, clock: Clock, confirm_base_url: str
    ) -> None:
        super().__init__(queue, EmailChannel(sender, confirm_base_url), clock)


class TelegramDispatcher(AlertDispatcher):
    """Atajo del dispatcher de Telegram."""

    def __init__(self, queue: DispatchQueue, api: TelegramSender, clock: Clock) -> None:
        super().__init__(queue, TelegramChannel(api), clock)
