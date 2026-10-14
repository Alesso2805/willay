from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from willay.alerts.application.policies import Actor
from willay.alerts.application.telegram_link import (
    ContactLinkState,
    ContactNotFoundError,
    TelegramNotConfiguredError,
    create_telegram_link,
    handle_start,
)
from willay.alerts.domain.delivery import hash_ack_token
from willay.alerts.domain.telegram import (
    MAX_START_PARAMETER,
    how_to_link,
    invalid_link,
    start_parameter,
)
from willay.shared.audit import AuditEntry
from willay.shared.clock import FakeClock
from willay.shared.languages import Language

T0 = datetime(2026, 12, 1, 15, 0, tzinfo=UTC)
TOKEN = "a" * 43


@pytest.mark.parametrize(
    ("text", "token"),
    [
        (f"/start {TOKEN}", TOKEN),
        (f"/start@WillayAlertsBot {TOKEN}", TOKEN),  # the form it takes in a group chat
        (f"  /start   {TOKEN}  ", TOKEN),
        ("/start", None),  # opened the bot without a link
        ("hello", None),
        ("/start " + "a" * 65, None),  # Telegram allows at most 64
    ],
)
def test_the_token_comes_in_the_start_command(text: str, token: str | None) -> None:
    assert start_parameter(text) == token


class Contacts:
    def __init__(self, organization_id: UUID) -> None:
        self.contact = ContactLinkState(
            contact_id=uuid4(),
            organization_id=organization_id,
            full_name="Lucho Quispe",
            organization_name="Demo Rímac",
            telegram_linked=False,
            link_expires_at=None,
            language=Language.ES,
        )
        self.token_hash: str | None = None
        self.chat_id: int | None = None

    async def get(
        self, organization_id: UUID, contact_id: UUID, *, for_update: bool = False
    ) -> ContactLinkState | None:
        mine = (organization_id, contact_id) == (
            self.contact.organization_id,
            self.contact.contact_id,
        )
        return self.contact if mine else None

    async def by_link_hash(self, token_hash: str) -> ContactLinkState | None:
        return self.contact if token_hash == self.token_hash else None

    async def store_link(self, contact_id: UUID, token_hash: str, expires_at: datetime) -> None:
        self.token_hash = token_hash
        self.contact = replace(self.contact, link_expires_at=expires_at)

    async def link_chat(self, contact_id: UUID, chat_id: int) -> None:
        self.chat_id, self.token_hash = chat_id, None
        self.contact = replace(self.contact, telegram_linked=True, link_expires_at=None)


class Audit:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


ACTOR = Actor(uuid4(), uuid4())


async def _link(contacts: Contacts, audit: Audit, clock: FakeClock) -> str:
    link = await create_telegram_link(
        ACTOR,
        contacts.contact.contact_id,
        contacts=contacts,
        audit=audit,
        clock=clock,
        bot_username="WillayAlertsBot",
    )
    assert link.expires_at == clock.now() + timedelta(days=7)
    assert link.url.startswith("https://t.me/WillayAlertsBot?start=")
    return link.url.rsplit("=", 1)[1]


async def test_a_link_stores_only_the_hash_and_is_audited_without_the_token() -> None:
    contacts, audit = Contacts(ACTOR.organization_id), Audit()
    token = await _link(contacts, audit, FakeClock(T0))

    assert contacts.token_hash == hash_ack_token(token)
    [entry] = audit.entries
    assert (entry.action, entry.actor_id) == ("telegram_link_created", ACTOR.user_id)
    assert token not in str(entry.after)


async def test_the_token_fits_telegram_start_parameter() -> None:
    # Telegram passes at most 64 characters after ?start= to the bot (VIG-21).
    token = await _link(Contacts(ACTOR.organization_id), Audit(), FakeClock(T0))
    assert len(token) <= MAX_START_PARAMETER
    assert start_parameter(f"/start {token}") == token


async def test_a_link_needs_the_bot_and_a_contact_of_the_organization() -> None:
    contacts, audit = Contacts(ACTOR.organization_id), Audit()
    with pytest.raises(TelegramNotConfiguredError):
        await create_telegram_link(
            ACTOR, uuid4(), contacts=contacts, audit=audit, clock=FakeClock(T0), bot_username=None
        )
    other = Contacts(uuid4())  # the contact belongs to another organization
    with pytest.raises(ContactNotFoundError):
        await create_telegram_link(
            ACTOR,
            other.contact.contact_id,
            contacts=other,
            audit=audit,
            clock=FakeClock(T0),
            bot_username="WillayAlertsBot",
        )


async def test_opening_the_link_links_the_chat_once() -> None:
    contacts, audit, clock = Contacts(ACTOR.organization_id), Audit(), FakeClock(T0)
    token = await _link(contacts, audit, clock)

    reply = await _start(42, f"/start {token}", contacts, audit, clock)
    assert reply.startswith("Listo, Lucho Quispe")
    assert "Demo Rímac" in reply
    assert contacts.chat_id == 42
    assert audit.entries[-1].action == "telegram_linked"
    assert "42" not in str(audit.entries[-1].after)  # the chat_id is personal data

    again = await _start(99, f"/start {token}", contacts, audit, clock)
    assert (again, contacts.chat_id) == (invalid_link(Language.ES), 42)


async def test_an_expired_or_missing_link_does_not_link() -> None:
    contacts, audit, clock = Contacts(ACTOR.organization_id), Audit(), FakeClock(T0)
    token = await _link(contacts, audit, clock)
    clock.advance(timedelta(days=7))

    assert await _start(42, f"/start {token}", contacts, audit, clock) == invalid_link(Language.ES)
    assert await _start(42, "/start", contacts, audit, clock) == how_to_link(Language.ES)
    assert contacts.chat_id is None


async def test_the_bot_speaks_the_sender_language_until_it_knows_the_contact() -> None:
    contacts, audit, clock = Contacts(ACTOR.organization_id), Audit(), FakeClock(T0)
    contacts.contact = replace(contacts.contact, language=Language.EN)
    # Nobody to tie the message to: the language of the sender's Telegram app.
    assert await _start(42, "hola", contacts, audit, clock, Language.EN) == how_to_link(Language.EN)
    assert await _start(42, "/start " + "x" * 43, contacts, audit, clock, Language.EN) == (
        invalid_link(Language.EN)
    )
    # Once linked, the language of their alerts, whatever their app's.
    token = await _link(contacts, audit, clock)
    reply = await _start(42, f"/start {token}", contacts, audit, clock, Language.ES)
    assert reply.startswith("Done, Lucho Quispe: from now on you will receive")


async def _start(
    chat_id: int,
    text: str,
    contacts: Contacts,
    audit: Audit,
    clock: FakeClock,
    sender_language: Language = Language.ES,
) -> str:
    return await handle_start(
        chat_id, text, sender_language=sender_language, contacts=contacts, audit=audit, clock=clock
    )
