"""El worker telegram atiende al bot (VIG-21; VIG-22 suma los clics de confirmación).

Long polling con `getUpdates`. Cada actualización se procesa en su propia transacción y
recién después se pide la siguiente: pedir desde `update_id + 1` es lo que confirma a
Telegram que ya se atendió. Si la base falla, la actualización no se confirma y se
reintenta. Si lo que falla es la respuesta al contacto, lo hecho en la base ya quedó y no
se reintenta (un segundo intento respondería "enlace no válido": ya se usó).

Solo se atienden conversaciones privadas con el bot: en un grupo nadie vincula nada.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from vigia.alerts.application.telegram_link import ContactLinkRepository, handle_start
from vigia.rules.application.evaluate import Transaction
from vigia.shared.audit import AuditLog
from vigia.shared.clock import Clock

log = structlog.get_logger()


class TelegramError(Exception):
    """Telegram no respondió o rechazó la llamada. Nunca incluye el token del bot."""


@dataclass(frozen=True)
class Update:
    update_id: int
    chat_id: int | None = None
    chat_type: str | None = None  # "private" en una conversación con el bot
    text: str | None = None


class TelegramApi(Protocol):
    async def get_updates(self, offset: int | None, timeout_s: int) -> list[Update]: ...

    async def send_message(self, chat_id: int, text: str) -> None: ...


class TelegramPoller:
    def __init__(
        self,
        api: TelegramApi,
        transaction: Transaction,
        clock: Clock,
        contacts: Callable[[AsyncConnection], ContactLinkRepository],
        audit: Callable[[AsyncConnection], AuditLog],
    ) -> None:
        self._api = api
        self._transaction = transaction
        self._clock = clock
        self._contacts = contacts
        self._audit = audit
        self._offset: int | None = None  # None: todo lo que Telegram aún no dio por atendido

    async def poll(self, timeout_s: int) -> int:
        updates = await self._api.get_updates(self._offset, timeout_s)
        for update in updates:
            await self._handle(update)  # si la base falla, no se confirma y se reintenta
            self._offset = update.update_id + 1
        return len(updates)

    async def _handle(self, update: Update) -> None:
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
