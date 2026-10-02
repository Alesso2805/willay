"""VIG-36: contact validation and use cases, with an in-memory repository."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from willay.alerts.application.contacts import (
    Contact,
    ContactGroupRef,
    ContactHasHistoryError,
    create_contact,
    delete_contact,
    remove_from_all_groups,
    unlink_telegram,
    update_contact,
)
from willay.alerts.application.policies import Actor
from willay.alerts.application.telegram_link import ContactNotFoundError
from willay.alerts.domain.contacts import ContactData, InvalidContactError, validate_contact
from willay.shared.audit import AuditEntry
from willay.shared.clock import FakeClock

T0 = datetime(2026, 12, 21, 10, 0, tzinfo=UTC)
ACTOR = Actor(uuid4(), uuid4())


class FakeContacts:
    def __init__(self, *contacts: Contact) -> None:
        self.by_id = {c.id: c for c in contacts}

    async def all_of(self, organization_id: UUID) -> list[Contact]:
        return sorted(self.by_id.values(), key=lambda c: c.full_name)

    async def get(
        self, organization_id: UUID, contact_id: UUID, *, for_update: bool = False
    ) -> Contact | None:
        return self.by_id.get(contact_id) if organization_id == ACTOR.organization_id else None

    async def add(self, contact_id: UUID, organization_id: UUID, data: ContactData) -> Contact:
        contact = Contact(contact_id, data.full_name, data.email, False, None, (), False)
        self.by_id[contact_id] = contact
        return contact

    async def replace(self, organization_id: UUID, contact_id: UUID, data: ContactData) -> Contact:
        self.by_id[contact_id] = replace(
            self.by_id[contact_id], full_name=data.full_name, email=data.email
        )
        return self.by_id[contact_id]

    async def delete(self, contact_id: UUID) -> None:
        del self.by_id[contact_id]

    async def remove_from_groups(self, organization_id: UUID, contact_id: UUID) -> Contact:
        self.by_id[contact_id] = replace(self.by_id[contact_id], groups=())
        return self.by_id[contact_id]

    async def unlink_telegram(self, organization_id: UUID, contact_id: UUID) -> Contact:
        self.by_id[contact_id] = replace(
            self.by_id[contact_id], telegram_linked=False, telegram_link_expires_at=None
        )
        return self.by_id[contact_id]


class FakeAudit:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


def _contact(**changes: object) -> Contact:
    base = Contact(uuid4(), "Rosa Brigada", "brigada@rimac.test", True, None, (), False)
    return replace(base, **changes)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("data", "field"),
    [
        (ContactData("", None), "full_name"),
        (ContactData("x" * 121, None), "full_name"),
        (ContactData("Rosa", "rosa@rimac"), "email"),
        (ContactData("Rosa", "rosa rimac@x.pe"), "email"),
    ],
)
def test_a_contact_needs_a_name_and_a_plausible_email(data: ContactData, field: str) -> None:
    with pytest.raises(InvalidContactError) as caught:
        validate_contact(data)
    assert caught.value.field == field


def test_a_contact_may_have_no_email() -> None:
    validate_contact(ContactData("Lucho Quispe", None))  # Telegram only, or no channel yet
    validate_contact(ContactData("Lucho Quispe", "lucho@quirio.pe"))


async def test_creating_records_the_contact_in_the_audit_log() -> None:
    contacts, audit = FakeContacts(), FakeAudit()
    contact = await create_contact(
        ACTOR, ContactData("Lucho", None), contacts=contacts, audit=audit, clock=FakeClock(T0)
    )
    assert [(e.action, e.before, e.after) for e in audit.entries] == [
        (
            "create",
            None,
            {"full_name": "Lucho", "email": None, "telegram_linked": False, "groups": []},
        )
    ]
    assert audit.entries[0].entity_id == contact.id


async def test_an_edit_that_changes_nothing_writes_nothing() -> None:
    rosa = _contact()
    contacts, audit = FakeContacts(rosa), FakeAudit()
    same = await update_contact(
        ACTOR, rosa.id, rosa.data, contacts=contacts, audit=audit, clock=FakeClock(T0)
    )
    assert same == rosa
    assert audit.entries == []


async def test_a_contact_with_history_is_not_deleted_and_nothing_else_changes() -> None:
    rosa = _contact(has_history=True, groups=(ContactGroupRef(uuid4(), "Brigada"),))
    contacts, audit = FakeContacts(rosa), FakeAudit()
    with pytest.raises(ContactHasHistoryError):
        await delete_contact(ACTOR, rosa.id, contacts=contacts, audit=audit, clock=FakeClock(T0))
    assert contacts.by_id[rosa.id] == rosa  # still in its groups: no side effect
    assert audit.entries == []


async def test_removing_from_all_groups_is_audited_once() -> None:
    rosa = _contact(has_history=True, groups=(ContactGroupRef(uuid4(), "Brigada"),))
    contacts, audit = FakeContacts(rosa), FakeAudit()
    removed = await remove_from_all_groups(
        ACTOR, rosa.id, contacts=contacts, audit=audit, clock=FakeClock(T0)
    )
    assert removed.groups == ()
    again = await remove_from_all_groups(
        ACTOR, rosa.id, contacts=contacts, audit=audit, clock=FakeClock(T0)
    )
    assert again.groups == ()
    assert [(e.action, e.before["groups"] if e.before else None) for e in audit.entries] == [
        ("removed_from_groups", ["Brigada"])
    ]


async def test_unlinking_telegram_is_audited_without_the_chat() -> None:
    rosa = _contact(telegram_linked=True)
    contacts, audit = FakeContacts(rosa), FakeAudit()
    unlinked = await unlink_telegram(
        ACTOR, rosa.id, contacts=contacts, audit=audit, clock=FakeClock(T0)
    )
    assert not unlinked.telegram_linked
    assert [e.action for e in audit.entries] == ["telegram_unlinked"]
    assert "chat" not in str(audit.entries[0].before) + str(audit.entries[0].after)


def test_a_pending_link_shows_until_it_expires() -> None:
    lucho = _contact(telegram_linked=False, telegram_link_expires_at=T0 + timedelta(days=7))
    assert lucho.pending_link_until(T0) == T0 + timedelta(days=7)
    assert lucho.pending_link_until(T0 + timedelta(days=8)) is None


async def test_another_organizations_contact_does_not_exist() -> None:
    contacts, audit = FakeContacts(_contact()), FakeAudit()
    stranger = Actor(uuid4(), uuid4())
    with pytest.raises(ContactNotFoundError):
        await delete_contact(
            stranger, next(iter(contacts.by_id)), contacts=contacts, audit=audit,
            clock=FakeClock(T0),
        )  # fmt: skip
