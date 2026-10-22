"""Contact use cases. Admin only, audited in the same transaction and scoped to the
actor's organization (another organization's contact does not exist: 404).

A contact with history (alerts, or an acknowledgement) is never deleted (SPEC): the timeline
must keep saying who was alerted and who acknowledged. To stop alerting them, they are removed
from their groups instead; that is an explicit action, never a side effect of a failed delete.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from uuid_utils.compat import uuid7

from willay.alerts.application.policies import Actor
from willay.alerts.application.telegram_link import ENTITY_TYPE, ContactNotFoundError
from willay.alerts.domain.contacts import ContactData, validate_contact
from willay.shared.audit import AuditEntry, AuditLog
from willay.shared.clock import Clock
from willay.shared.languages import Language


@dataclass(frozen=True)
class ContactGroupRef:
    id: UUID
    name: str


@dataclass(frozen=True)
class Contact:
    id: UUID
    full_name: str
    email: str | None
    language: Language | None
    telegram_linked: bool
    # When the last link generated for it expires, while it is not linked; may be past.
    telegram_link_expires_at: datetime | None
    groups: tuple[ContactGroupRef, ...]
    has_history: bool

    @property
    def data(self) -> ContactData:
        return ContactData(self.full_name, self.email, self.language)

    def pending_link_until(self, now: datetime) -> datetime | None:
        """Until when the link sent to the contact still works, if there is one."""
        expires = self.telegram_link_expires_at
        return expires if expires is not None and expires > now else None

    def snapshot(self) -> dict[str, Any]:
        """What the audit log stores. Whether Telegram is linked, never the chat."""
        return {
            "full_name": self.full_name,
            "email": self.email,
            "language": self.language,
            "telegram_linked": self.telegram_linked,
            "groups": [group.name for group in self.groups],
        }


class ContactHasHistoryError(Exception):
    def __init__(self, contact: Contact) -> None:
        super().__init__(contact.full_name)
        self.contact = contact


class ContactRepository(Protocol):
    async def all_of(self, organization_id: UUID) -> list[Contact]:
        """By name."""
        ...

    async def get(
        self, organization_id: UUID, contact_id: UUID, *, for_update: bool = False
    ) -> Contact | None: ...

    async def add(self, contact_id: UUID, organization_id: UUID, data: ContactData) -> Contact: ...

    async def replace(
        self, organization_id: UUID, contact_id: UUID, data: ContactData
    ) -> Contact: ...

    async def delete(self, contact_id: UUID) -> None:
        """Its group memberships go with it."""
        ...

    async def remove_from_groups(self, organization_id: UUID, contact_id: UUID) -> Contact: ...

    async def unlink_telegram(self, organization_id: UUID, contact_id: UUID) -> Contact:
        """Forgets the chat and any pending link."""
        ...


async def create_contact(
    actor: Actor, data: ContactData, *, contacts: ContactRepository, audit: AuditLog, clock: Clock
) -> Contact:
    validate_contact(data)
    contact = await contacts.add(uuid7(), actor.organization_id, data)
    await audit.record(_entry(actor, contact.id, "create", None, contact, clock.now()))
    return contact


async def update_contact(
    actor: Actor,
    contact_id: UUID,
    data: ContactData,
    *,
    contacts: ContactRepository,
    audit: AuditLog,
    clock: Clock,
) -> Contact:
    current = await _locked(actor, contact_id, contacts)
    if current.data == data:
        return current  # no changes: no write and no empty audit entry
    validate_contact(data)
    updated = await contacts.replace(actor.organization_id, contact_id, data)
    await audit.record(_entry(actor, contact_id, "update", current, updated, clock.now()))
    return updated


async def delete_contact(
    actor: Actor, contact_id: UUID, *, contacts: ContactRepository, audit: AuditLog, clock: Clock
) -> None:
    current = await _locked(actor, contact_id, contacts)
    if current.has_history:
        raise ContactHasHistoryError(current)
    await contacts.delete(contact_id)
    await audit.record(_entry(actor, contact_id, "delete", current, None, clock.now()))


async def remove_from_all_groups(
    actor: Actor, contact_id: UUID, *, contacts: ContactRepository, audit: AuditLog, clock: Clock
) -> Contact:
    """What stops alerting a contact that cannot be deleted."""
    current = await _locked(actor, contact_id, contacts)
    if not current.groups:
        return current
    updated = await contacts.remove_from_groups(actor.organization_id, contact_id)
    await audit.record(
        _entry(actor, contact_id, "removed_from_groups", current, updated, clock.now())
    )
    return updated


async def unlink_telegram(
    actor: Actor, contact_id: UUID, *, contacts: ContactRepository, audit: AuditLog, clock: Clock
) -> Contact:
    current = await _locked(actor, contact_id, contacts)
    if not current.telegram_linked and current.telegram_link_expires_at is None:
        return current
    updated = await contacts.unlink_telegram(actor.organization_id, contact_id)
    await audit.record(
        _entry(actor, contact_id, "telegram_unlinked", current, updated, clock.now())
    )
    return updated


async def _locked(actor: Actor, contact_id: UUID, contacts: ContactRepository) -> Contact:
    # FOR UPDATE: two admins acting on the same contact don't clobber the audited "before".
    contact = await contacts.get(actor.organization_id, contact_id, for_update=True)
    if contact is None:
        raise ContactNotFoundError(contact_id)
    return contact


def _entry(
    actor: Actor,
    contact_id: UUID,
    action: str,
    before: Contact | None,
    after: Contact | None,
    at: datetime,
) -> AuditEntry:
    return AuditEntry(
        organization_id=actor.organization_id,
        actor_id=actor.user_id,
        entity_type=ENTITY_TYPE,
        entity_id=contact_id,
        action=action,
        before=before.snapshot() if before is not None else None,
        after=after.snapshot() if after is not None else None,
        at=at,
    )
