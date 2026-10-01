"""ContactLinkRepository over core.contacts (vigia_app role)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncConnection

from vigia.alerts.application.telegram_link import ContactLinkState

_SELECT = """
    SELECT c.id, c.organization_id, c.full_name, o.name AS organization_name,
           c.telegram_chat_id IS NOT NULL AS telegram_linked, c.telegram_link_expires_at
    FROM core.contacts c
    JOIN core.organizations o ON o.id = c.organization_id
"""
_GET = text(_SELECT + " WHERE c.organization_id = :organization_id AND c.id = :id")
_GET_LOCKED = text(
    _SELECT + " WHERE c.organization_id = :organization_id AND c.id = :id FOR UPDATE OF c"
)
# Locked: two /start with the same link (double tap) cannot use it twice.
_BY_HASH = text(_SELECT + " WHERE c.telegram_link_token_hash = :hash FOR UPDATE OF c")
_STORE = text("""
    UPDATE core.contacts
    SET telegram_link_token_hash = :hash, telegram_link_expires_at = :expires_at
    WHERE id = :id
""")
_LINK = text("""
    UPDATE core.contacts
    SET telegram_chat_id = :chat_id, telegram_link_token_hash = NULL,
        telegram_link_expires_at = NULL
    WHERE id = :id
""")


class SqlContactLinkRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get(
        self, organization_id: UUID, contact_id: UUID, *, for_update: bool = False
    ) -> ContactLinkState | None:
        query = _GET_LOCKED if for_update else _GET
        row = (
            await self._conn.execute(query, {"organization_id": organization_id, "id": contact_id})
        ).first()
        return _state(row) if row is not None else None

    async def by_link_hash(self, token_hash: str) -> ContactLinkState | None:
        row = (await self._conn.execute(_BY_HASH, {"hash": token_hash})).first()
        return _state(row) if row is not None else None

    async def store_link(self, contact_id: UUID, token_hash: str, expires_at: datetime) -> None:
        await self._conn.execute(
            _STORE, {"id": contact_id, "hash": token_hash, "expires_at": expires_at}
        )

    async def link_chat(self, contact_id: UUID, chat_id: int) -> None:
        await self._conn.execute(_LINK, {"id": contact_id, "chat_id": chat_id})


def _state(row: Row[Any]) -> ContactLinkState:
    return ContactLinkState(
        contact_id=row.id,
        organization_id=row.organization_id,
        full_name=row.full_name,
        organization_name=row.organization_name,
        telegram_linked=row.telegram_linked,
        link_expires_at=row.telegram_link_expires_at,
    )
