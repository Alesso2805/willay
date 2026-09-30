"""El worker telegram atiende al bot: vincula contactos (VIG-21) y recibe los clics en
el botón de confirmación de las alertas (VIG-22).

Long polling con `getUpdates`. Cada actualización se procesa en su propia transacción y
recién después se pide la siguiente: pedir desde `update_id + 1` es lo que confirma a
Telegram que ya se atendió. Si la base falla, la actualización no se confirma y se
reintenta. Si lo que falla es la respuesta al contacto, lo hecho en la base ya quedó y no
se reintenta (un segundo intento respondería "enlace no válido": ya se usó).

Solo se atienden conversaciones privadas con el bot: en un grupo nadie vincula nada.
Un clic confirma solo si lo hace el destinatario de la alerta: en un chat privado el
`chat_id` es el id de la persona, así que se compara con quien pulsó (`from.id`).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from vigia.alerts.application.confirmation import (
    ConfirmationRepository,
    ConfirmationView,
    confirm_alert,
)
from vigia.alerts.application.telegram_link import ContactLinkRepository, handle_start
from vigia.alerts.domain.confirmation import ConfirmOutcome
from vigia.alerts.domain.telegram import CLICK_ANSWER, closing_note
from vigia.incidents.application.lifecycle import IncidentRepository
from vigia.rules.application.evaluate import Transaction
from vigia.shared.audit import AuditLog
from vigia.shared.clock import Clock

log = structlog.get_logger()


class TelegramError(Exception):
    """Telegram no respondió o rechazó la llamada. Nunca incluye el token del bot."""


@dataclass(frozen=True)
class Click:
    """Un clic en el botón de una alerta (`callback_query`)."""

    id: str  # para responderlo con answerCallbackQuery
    from_id: int  # quién pulsó
    data: str | None  # el token de la alerta
    chat_id: int | None = None  # el mensaje del botón, para editarlo
    message_id: int | None = None
    message_text: str | None = None  # None si Telegram ya no lo entrega


@dataclass(frozen=True)
class Update:
    update_id: int
    chat_id: int | None = None
    chat_type: str | None = None  # "private" en una conversación con el bot
    text: str | None = None
    click: Click | None = None


class TelegramApi(Protocol):
    async def get_updates(self, offset: int | None, timeout_s: int) -> list[Update]: ...

    async def send_message(self, chat_id: int, text: str) -> None: ...

    async def answer_click(self, click_id: str, text: str) -> None: ...

    async def edit_message(self, chat_id: int, message_id: int, text: str) -> None:
        """Reemplaza el texto y quita el botón."""
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
        self._offset: int | None = None  # None: todo lo que Telegram aún no dio por atendido

    async def poll(self, timeout_s: int) -> int:
        updates = await self._api.get_updates(self._offset, timeout_s)
        for update in updates:
            await self._handle(update)  # si la base falla, no se confirma y se reintenta
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
            # Nunca el chat_id: es un dato personal.
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
        # Lo hecho en la base ya quedó: si Telegram falla al responder, no se reintenta.
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
            text = f"{click.message_text}\n\n{note}"
            await self._api.edit_message(click.chat_id, click.message_id, text)
        except TelegramError as exc:
            log.warning("telegram_edit_failed", update_id=update_id, error=str(exc))
