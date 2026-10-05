"""Sending pending alerts by email (VIG-20) and Telegram (VIG-22) with the same pattern.

Like the readings queue (ADR-0002), each alert goes through short transactions:
1. claim: SKIP LOCKED, `attempts + 1` and a 60 s visibility timeout, so no other
   dispatcher takes it while sending, and it is retried if this one dies;
2. token: the confirmation token hash is stored BEFORE sending, so the link always works;
3. send through the channel outside any transaction (slow SMTP holds no connections);
4. result: `sent`, retry with backoff, or `failed` once attempts run out, with its event.

Steps 2-4 require the claim to still be ours (`attempts` unchanged). A batch is sent in
parallel: serially, a slow SMTP could exceed the visibility timeout and let another
dispatcher claim alerts still being sent.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

import structlog

from willay.alerts.application.telegram_bot import TelegramError
from willay.alerts.domain.alerts import Channel
from willay.alerts.domain.delivery import AckToken, new_ack_token, retry_at
from willay.alerts.domain.email import AlertMessage, EmailContent, compose_email
from willay.alerts.domain.telegram import compose_alert_text, confirm_button
from willay.shared.clock import Clock

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
    correlation_id: UUID | None = None  # its incident's (VIG-28)
    # When the reading that opened its incident arrived; None for silence (VIG-28).
    trigger_received_at: datetime | None = None


class DeliveryError(Exception):
    """The channel did not deliver the message. The text must not include the destination
    (personal data)."""


class DispatchQueue(Protocol):
    async def claim(
        self, channel: Channel, now: datetime, visible_again_at: datetime, limit: int
    ) -> list[ClaimedAlert]:
        """Claims due pending alerts of open incidents. First it skips pending alerts of
        acknowledged or resolved incidents and fails those that used up their attempts
        without a result (the worker died mid-send)."""
        ...

    async def attach_token(self, alert: ClaimedAlert, token: AckToken) -> bool:
        """Stores the token hash. False if the claim is no longer ours."""
        ...

    async def sent(self, alert: ClaimedAlert, now: datetime) -> bool:
        """Records it as sent. True if it is the first alert of its incident to be sent."""
        ...

    async def failed(
        self, alert: ClaimedAlert, error: str, retry: datetime | None, now: datetime
    ) -> None:
        """Retry at `retry`, or permanently `failed` if it is None."""
        ...


class EmailSender(Protocol):
    async def send(self, to: str, content: EmailContent) -> None:
        """Raises DeliveryError if the server did not accept the message."""
        ...


@dataclass(frozen=True)
class DispatchResult:
    claimed: int
    sent: int
    failed: int


class DeliveryChannel(Protocol):
    """How an alert is delivered through a channel: builds its message and sends it."""

    @property
    def channel(self) -> Channel: ...

    async def deliver(self, destination: str, message: AlertMessage, token: str) -> None:
        """Raises DeliveryError if the channel did not accept it."""
        ...


class EmailChannel:
    """Email with a link to the confirmation page (VIG-20, VIG-23)."""

    channel = Channel.EMAIL

    def __init__(self, sender: EmailSender, confirm_base_url: str) -> None:
        self._sender = sender
        self._confirm_base_url = confirm_base_url.rstrip("/")

    async def deliver(self, destination: str, message: AlertMessage, token: str) -> None:
        confirm_url = f"{self._confirm_base_url}/confirmar/{token}"
        await self._sender.send(destination, compose_email(message, confirm_url))


class TelegramSender(Protocol):
    async def send_alert(self, chat_id: int, text: str, callback_data: str, button: str) -> None:
        """Raises TelegramError if Telegram did not accept the message."""
        ...


class TelegramChannel:
    """Telegram message with a button whose `callback_data` is the token (VIG-22): 43
    chars, within Telegram's 64-char limit."""

    channel = Channel.TELEGRAM

    def __init__(self, api: TelegramSender) -> None:
        self._api = api

    async def deliver(self, destination: str, message: AlertMessage, token: str) -> None:
        try:
            await self._api.send_alert(
                int(destination),
                compose_alert_text(message),
                token,
                confirm_button(message.language),
            )
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
                # An unexpected error does not lose the alert: retried once the claim expires.
                log.error("alert_dispatch_crashed", alert_id=str(alert.alert_id), exc_info=outcome)
        return DispatchResult(
            claimed=len(claimed),
            sent=sum(1 for o in outcomes if o is True),
            failed=sum(1 for o in outcomes if o is False),
        )

    async def _deliver(self, alert: ClaimedAlert) -> bool | None:
        """True if sent, False if it failed, None if the claim was no longer ours."""
        token = new_ack_token(self._clock.now())
        if not await self._queue.attach_token(alert, token):
            return None
        bound = log.bind(
            alert_id=str(alert.alert_id),
            attempt=alert.attempt,
            channel=alert.channel.value,
            correlation_id=str(alert.correlation_id) if alert.correlation_id else None,
        )
        try:
            await self._channel.deliver(alert.destination, alert.message, token.token)
        except DeliveryError as exc:
            now = self._clock.now()
            retry = retry_at(alert.attempt, now)
            await self._queue.failed(alert, str(exc), retry, now)
            bound.warning("alert_send_failed", error=str(exc), final=retry is None)
            return False
        sent_at = self._clock.now()
        first = await self._queue.sent(alert, sent_at)
        latency = {}
        if first and alert.trigger_received_at is not None:
            # SPEC's latency: reading received → first alert sent (p95 < 30 s).
            seconds = (sent_at - alert.trigger_received_at).total_seconds()
            latency = {"received_to_alert_seconds": round(seconds, 3)}
        bound.info("alert_sent", incident_id=str(alert.incident_id), **latency)
        return True


class EmailDispatcher(AlertDispatcher):
    """Shortcut for the email dispatcher."""

    def __init__(
        self, queue: DispatchQueue, sender: EmailSender, clock: Clock, confirm_base_url: str
    ) -> None:
        super().__init__(queue, EmailChannel(sender, confirm_base_url), clock)


class TelegramDispatcher(AlertDispatcher):
    """Shortcut for the Telegram dispatcher."""

    def __init__(self, queue: DispatchQueue, api: TelegramSender, clock: Clock) -> None:
        super().__init__(queue, TelegramChannel(api), clock)
