"""Linking a contact's Telegram (VIG-21).

- `create_telegram_link` (admin): single-use link; only its token hash is stored, so it is
  shown once. A new link invalidates the previous one.
- `handle_start` (telegram worker): a valid `/start <token>` stores the contact's `chat_id`
  and voids the token. It always replies something useful: a person, not an API, is typing.

Every contact change is audited (SPEC). The `chat_id` is personal data: audit and logs only
record whether the contact is linked.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from willay.alerts.application.policies import Actor
from willay.alerts.domain.delivery import hash_ack_token, new_token
from willay.alerts.domain.telegram import (
    HOW_TO_LINK,
    INVALID_LINK,
    LINK_TTL,
    LINKED,
    deep_link,
    start_parameter,
)
from willay.shared.audit import AuditEntry, AuditLog
from willay.shared.clock import Clock

ENTITY_TYPE = "contact"


@dataclass(frozen=True)
class ContactLinkState:
    contact_id: UUID
    organization_id: UUID
    full_name: str
    organization_name: str
    telegram_linked: bool
    link_expires_at: datetime | None


class ContactLinkRepository(Protocol):
    async def get(
        self, organization_id: UUID, contact_id: UUID, *, for_update: bool = False
    ) -> ContactLinkState | None: ...

    async def by_link_hash(self, token_hash: str) -> ContactLinkState | None:
        """The contact whose link has this hash, locked until the transaction ends."""
        ...

    async def store_link(self, contact_id: UUID, token_hash: str, expires_at: datetime) -> None: ...

    async def link_chat(self, contact_id: UUID, chat_id: int) -> None:
        """Stores the chat_id and voids the link: it is single use."""
        ...


class ContactNotFoundError(Exception):
    pass


class TelegramNotConfiguredError(Exception):
    """Without the bot username the link cannot be built."""


@dataclass(frozen=True)
class TelegramLink:
    url: str
    expires_at: datetime


async def create_telegram_link(
    actor: Actor,
    contact_id: UUID,
    *,
    contacts: ContactLinkRepository,
    audit: AuditLog,
    clock: Clock,
    bot_username: str | None,
) -> TelegramLink:
    if not bot_username:
        raise TelegramNotConfiguredError
    contact = await contacts.get(actor.organization_id, contact_id, for_update=True)
    if contact is None:
        raise ContactNotFoundError(contact_id)
    now = clock.now()
    token = new_token(now, LINK_TTL)
    await contacts.store_link(contact_id, token.token_hash, token.expires_at)
    await audit.record(
        AuditEntry(
            organization_id=actor.organization_id,
            actor_id=actor.user_id,
            entity_type=ENTITY_TYPE,
            entity_id=contact_id,
            action="telegram_link_created",
            before={"telegram_linked": contact.telegram_linked},
            after={
                "telegram_linked": contact.telegram_linked,
                "telegram_link_expires_at": token.expires_at.isoformat(),
            },
            at=now,
        )
    )
    return TelegramLink(deep_link(bot_username, token.token), token.expires_at)


async def handle_start(
    chat_id: int, text: str, *, contacts: ContactLinkRepository, audit: AuditLog, clock: Clock
) -> str:
    """The bot's reply to a private message."""
    token = start_parameter(text)
    if token is None:
        return HOW_TO_LINK
    contact = await contacts.by_link_hash(hash_ack_token(token))
    now = clock.now()
    if contact is None or contact.link_expires_at is None or now >= contact.link_expires_at:
        return INVALID_LINK
    await contacts.link_chat(contact.contact_id, chat_id)
    await audit.record(
        AuditEntry(
            organization_id=contact.organization_id,
            actor_id=None,  # requested by the contact themselves from Telegram
            entity_type=ENTITY_TYPE,
            entity_id=contact.contact_id,
            action="telegram_linked",
            before={"telegram_linked": contact.telegram_linked},
            after={"telegram_linked": True},
            at=now,
        )
    )
    return LINKED.format(name=contact.full_name, organization=contact.organization_name)
