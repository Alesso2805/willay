"""The telegram worker serves the bot: links contacts (VIG-21) and receives clicks on alert
confirmation buttons (VIG-22).

Long polling with `getUpdates`; asking from `update_id + 1` acknowledges the previous update
to Telegram, so each one is committed before the next is requested and a database failure
means a retry. A failed reply is not retried (a second try would answer "invalid link").
Only private chats are served. A click confirms only if made by the recipient: in a
private chat `chat_id` equals the person's id, so it is compared with `from.id`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from willay.alerts.application.confirmation import (
    ConfirmationRepository,
    ConfirmationView,
    confirm_alert,
)
from willay.alerts.application.telegram_link import ContactLinkRepository, handle_start
from willay.alerts.domain.confirmation import ConfirmOutcome
from willay.alerts.domain.telegram import CLICK_ANSWER, closed_text, closing_note
from willay.incidents.application.lifecycle import IncidentRepository
from willay.rules.application.evaluate import Transaction
from willay.shared.audit import AuditLog
from willay.shared.clock import Clock

log = structlog.get_logger()


class TelegramError(Exception):
    """Telegram did not respond or rejected the call. Never includes the bot token."""


@dataclass(frozen=True)
class Click:
    """A click on an alert's button (`callback_query`)."""

    id: str  # to answer it with answerCallbackQuery
    from_id: int  # who clicked
    data: str | None  # the alert token
    chat_id: int | None = None  # the button's message, to edit it
    message_id: int | None = None
    message_text: str | None = None  # None if Telegram no longer provides it


@dataclass(frozen=True)
class Update:
    update_id: int
    chat_id: int | None = None
    chat_type: str | None = None  # "private" in a one-to-one chat with the bot
    text: str | None = None
    click: Click | None = None


class TelegramApi(Protocol):
    async def get_updates(self, offset: int | None, timeout_s: int) -> list[Update]: ...

    async def send_message(self, chat_id: int, text: str) -> None: ...

    async def answer_click(self, click_id: str, text: str) -> None: ...

    async def edit_message(self, chat_id: int, message_id: int, text: str) -> None:
        """Replaces the text and removes the button."""
        ...


class TelegramPoller:
    def __init__(
        self,
        api: TelegramApi,
        transaction: Transaction,
        clock: Clock,
        contacts: Callable[[AsyncConnection], ContactLinkRepository],
        audit: Callable[[AsyncConnection], AuditLog],
        confirmations: Callable[[AsyncConnection], ConfirmationRepository],
        incidents: Callable[[AsyncConnection], IncidentRepository],
    ) -> None:
        self._api = api
        self._transaction = transaction
        self._clock = clock
        self._contacts = contacts
        self._audit = audit
        self._confirmations = confirmations
        self._incidents = incidents
        self._offset: int | None = None  # None: everything Telegram has not marked as handled

    async def poll(self, timeout_s: int) -> int:
        updates = await self._api.get_updates(self._offset, timeout_s)
        for update in updates:
            await self._handle(update)  # on a database failure it is not acked and is retried
            self._offset = update.update_id + 1
        return len(updates)

    async def _handle(self, update: Update) -> None:
        if update.click is not None:
            await self._confirm(update.update_id, update.click)
            return
        if update.chat_id is None or update.text is None or update.chat_type != "private":
            return
        async with self._transaction() as tx:
            reply = await handle_start(
                update.chat_id,
                update.text,
                contacts=self._contacts(tx),
                audit=self._audit(tx),
                clock=self._clock,
            )
        try:
            await self._api.send_message(update.chat_id, reply)
        except TelegramError as exc:
            # Never log the chat_id: it is personal data.
            log.warning("telegram_reply_failed", update_id=update.update_id, error=str(exc))

    async def _confirm(self, update_id: int, click: Click) -> None:
        view = ConfirmationView(ConfirmOutcome.UNKNOWN, None)
        if click.data is not None:
            async with self._transaction() as tx:
                view = await confirm_alert(
                    click.data,
                    confirmations=self._confirmations(tx),
                    incidents=self._incidents(tx),
                    clock=self._clock,
                    expected_destination=str(click.from_id),
                )
        alert = view.alert
        log.info(
            "telegram_click",
            update_id=update_id,
            outcome=view.outcome,
            alert_id=str(alert.alert_id) if alert is not None else None,
        )
        # The database work is committed: a failed Telegram reply is not retried.
        outcome = view.outcome or ConfirmOutcome.UNKNOWN
        try:
            await self._api.answer_click(click.id, CLICK_ANSWER[outcome])
        except TelegramError as exc:
            log.warning("telegram_answer_failed", update_id=update_id, error=str(exc))
        if alert is None or click.chat_id is None or click.message_id is None:
            return
        note = closing_note(
            outcome, alert.acknowledged_by, alert.incident_acknowledged_at, alert.message.timezone
        )
        if note is None or click.message_text is None:
            return
        try:
            text = closed_text(click.message_text, note)
            await self._api.edit_message(click.chat_id, click.message_id, text)
        except TelegramError as exc:
            log.warning("telegram_edit_failed", update_id=update_id, error=str(exc))
