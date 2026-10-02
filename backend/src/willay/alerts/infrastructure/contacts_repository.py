"""ContactRepository over core.contacts and its group memberships (VIG-36)."""

from typing import Any
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncConnection

from willay.alerts.application.contacts import Contact, ContactGroupRef
from willay.alerts.domain.contacts import ContactData

# History = anything that names the contact: an alert, an acknowledgement, a timeline event.
# The chat itself never leaves this query: only whether there is one.
_SELECT = """
    SELECT c.id, c.full_name, c.email,
           c.telegram_chat_id IS NOT NULL AS telegram_linked,
           CASE WHEN c.telegram_chat_id IS NULL THEN c.telegram_link_expires_at END
               AS telegram_link_expires_at,
           COALESCE((SELECT jsonb_agg(jsonb_build_object('id', g.id, 'name', g.name)
                                      ORDER BY g.name)
                     FROM core.contact_group_members m
                     JOIN core.contact_groups g ON g.id = m.group_id
                     WHERE m.contact_id = c.id), '[]'::jsonb) AS groups,
           (EXISTS (SELECT 1 FROM core.alerts a WHERE a.contact_id = c.id)
            OR EXISTS (SELECT 1 FROM core.incidents i WHERE i.acknowledged_by_contact_id = c.id)
            OR EXISTS (SELECT 1 FROM core.incident_events e
                       WHERE e.actor_type = 'contact' AND e.actor_id = c.id)) AS has_history
    FROM core.contacts c
"""

_ALL = text(_SELECT + " WHERE c.organization_id = :organization_id ORDER BY c.full_name, c.id")
_GET = text(_SELECT + " WHERE c.organization_id = :organization_id AND c.id = :id")
_GET_FOR_UPDATE = text(
    _SELECT + " WHERE c.organization_id = :organization_id AND c.id = :id FOR UPDATE OF c"
)

_ADD = text("""
    INSERT INTO core.contacts (id, organization_id, full_name, email)
    VALUES (:id, :organization_id, :full_name, :email)
""")

_REPLACE = text("""
    UPDATE core.contacts SET full_name = :full_name, email = :email
    WHERE organization_id = :organization_id AND id = :id
""")

_DELETE = text("DELETE FROM core.contacts WHERE id = :id")  # memberships cascade

_REMOVE_FROM_GROUPS = text("DELETE FROM core.contact_group_members WHERE contact_id = :id")

_UNLINK_TELEGRAM = text("""
    UPDATE core.contacts
    SET telegram_chat_id = NULL, telegram_link_token_hash = NULL, telegram_link_expires_at = NULL
    WHERE organization_id = :organization_id AND id = :id
""")


class SqlContactRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def all_of(self, organization_id: UUID) -> list[Contact]:
        rows = await self._conn.execute(_ALL, {"organization_id": organization_id})
        return [_contact(r) for r in rows]

    async def get(
        self, organization_id: UUID, contact_id: UUID, *, for_update: bool = False
    ) -> Contact | None:
        query = _GET_FOR_UPDATE if for_update else _GET
        row = (
            await self._conn.execute(query, {"organization_id": organization_id, "id": contact_id})
        ).first()
        return _contact(row) if row is not None else None

    async def add(self, contact_id: UUID, organization_id: UUID, data: ContactData) -> Contact:
        await self._conn.execute(
            _ADD,
            {
                "id": contact_id,
                "organization_id": organization_id,
                "full_name": data.full_name,
                "email": data.email,
            },
        )
        return await self._reload(organization_id, contact_id)

    async def replace(self, organization_id: UUID, contact_id: UUID, data: ContactData) -> Contact:
        await self._conn.execute(
            _REPLACE,
            {
                "organization_id": organization_id,
                "id": contact_id,
                "full_name": data.full_name,
                "email": data.email,
            },
        )
        return await self._reload(organization_id, contact_id)

    async def delete(self, contact_id: UUID) -> None:
        await self._conn.execute(_DELETE, {"id": contact_id})

    async def remove_from_groups(self, organization_id: UUID, contact_id: UUID) -> Contact:
        await self._conn.execute(_REMOVE_FROM_GROUPS, {"id": contact_id})
        return await self._reload(organization_id, contact_id)

    async def unlink_telegram(self, organization_id: UUID, contact_id: UUID) -> Contact:
        await self._conn.execute(
            _UNLINK_TELEGRAM, {"organization_id": organization_id, "id": contact_id}
        )
        return await self._reload(organization_id, contact_id)

    async def _reload(self, organization_id: UUID, contact_id: UUID) -> Contact:
        contact = await self.get(organization_id, contact_id)
        if contact is None:  # impossible in the same transaction
            raise LookupError(contact_id)
        return contact


def _contact(r: Row[Any]) -> Contact:
    return Contact(
        id=r.id,
        full_name=r.full_name,
        email=r.email,
        telegram_linked=r.telegram_linked,
        telegram_link_expires_at=r.telegram_link_expires_at,
        groups=tuple(ContactGroupRef(UUID(g["id"]), g["name"]) for g in r.groups),
        has_history=r.has_history,
    )
