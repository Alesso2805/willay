"""VIG-21: el worker telegram vincula contactos, contra Postgres real y un Telegram falso."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import Database
from tests.integration.factories import create_contact, create_graph
from vigia.alerts.application.policies import Actor
from vigia.alerts.application.telegram_bot import TelegramError, Update
from vigia.alerts.application.telegram_link import create_telegram_link
from vigia.alerts.domain.telegram import HOW_TO_LINK, INVALID_LINK
from vigia.alerts.infrastructure.sql_contact_links import SqlContactLinkRepository
from vigia.shared.audit import SqlAuditLog
from vigia.shared.clock import FakeClock, SystemClock
from vigia.shared.config import Settings
from vigia.shared.db import create_engine
from vigia.workers.telegram import run_telegram

pytestmark = pytest.mark.integration


class FakeTelegram:
    """Lo mínimo de la Bot API: entrega actualizaciones hasta que se confirman."""

    def __init__(self, *updates: Update, fail_replies: bool = False) -> None:
        self.pending = list(updates)
        self.offsets: list[int | None] = []
        self.replies: list[tuple[int, str]] = []
        self.fail_replies = fail_replies

    async def get_updates(self, offset: int | None, timeout_s: int) -> list[Update]:
        self.offsets.append(offset)
        if offset is not None:  # pedir desde `offset` confirma las anteriores
            self.pending = [u for u in self.pending if u.update_id >= offset]
        if not self.pending:
            await asyncio.sleep(0.02)  # long polling sin novedades
        return list(self.pending)

    async def send_message(self, chat_id: int, text: str) -> None:
        if self.fail_replies:
            raise TelegramError("sendMessage: 500 Internal Server Error")
        self.replies.append((chat_id, text))


@pytest.fixture
async def engine(database: Database) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


async def _contact_with_link(
    engine: AsyncEngine, owner: asyncpg.Connection, *, expired: bool = False
) -> tuple[UUID, str]:
    graph = await create_graph(owner)
    contact = await create_contact(owner, graph, "Lucho Quispe")
    now = SystemClock().now() - (timedelta(days=8) if expired else timedelta())
    async with engine.begin() as tx:
        link = await create_telegram_link(
            Actor(graph.organization_id, graph.organization_id),  # actor irrelevante aquí
            contact,
            contacts=SqlContactLinkRepository(tx),
            audit=SqlAuditLog(tx),
            clock=FakeClock(now),
            bot_username="VigiaAlertasBot",
        )
    return contact, link.url.rsplit("=", 1)[1]


async def _run_until(
    database: Database, tmp_path: Path, api: FakeTelegram, done: Callable[[], Awaitable[bool]]
) -> None:
    settings = Settings(database_url=database.app_url, heartbeat_dir=tmp_path)
    stop = asyncio.Event()
    worker = asyncio.create_task(run_telegram(settings, stop, api=api, poll_timeout_s=1))
    try:
        deadline = asyncio.get_running_loop().time() + 10
        while not await done():
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("el worker no terminó a tiempo")
            await asyncio.sleep(0.02)
    finally:
        stop.set()
        await worker


async def _chat_of(owner: asyncpg.Connection, contact: UUID) -> asyncpg.Record:
    row = await owner.fetchrow(
        "SELECT telegram_chat_id, telegram_link_token_hash FROM core.contacts WHERE id = $1",
        contact,
    )
    assert row is not None
    return row


async def test_opening_the_link_links_the_chat_and_confirms_the_update(
    engine: AsyncEngine, owner: asyncpg.Connection, database: Database, tmp_path: Path
) -> None:
    contact, token = await _contact_with_link(engine, owner)
    api = FakeTelegram(Update(100, 4242, "private", f"/start {token}"))

    async def linked_and_confirmed() -> bool:
        return 101 in api.offsets

    await _run_until(database, tmp_path, api, linked_and_confirmed)

    row = await _chat_of(owner, contact)
    assert (row["telegram_chat_id"], row["telegram_link_token_hash"]) == (4242, None)
    [(chat, reply)] = api.replies
    assert chat == 4242
    assert reply.startswith("Listo, Lucho Quispe")
    assert api.offsets[0] is None  # arrancó pidiendo lo que Telegram no dio por atendido
    audit = await owner.fetchval(
        "SELECT count(*) FROM core.audit_log WHERE entity_id = $1 AND action = 'telegram_linked'",
        contact,
    )
    assert audit == 1


@pytest.mark.parametrize(
    ("text", "reply"),
    [("/start " + "x" * 43, INVALID_LINK), ("/start", HOW_TO_LINK), ("hola", HOW_TO_LINK)],
    ids=["token-desconocido", "sin-token", "otro-mensaje"],
)
async def test_other_messages_get_a_helpful_reply(
    database: Database, tmp_path: Path, text: str, reply: str
) -> None:
    api = FakeTelegram(Update(200, 7, "private", text))

    async def replied() -> bool:
        return bool(api.replies)

    await _run_until(database, tmp_path, api, replied)
    assert api.replies == [(7, reply)]


async def test_an_expired_link_does_not_link(
    engine: AsyncEngine, owner: asyncpg.Connection, database: Database, tmp_path: Path
) -> None:
    contact, token = await _contact_with_link(engine, owner, expired=True)
    api = FakeTelegram(Update(300, 4242, "private", f"/start {token}"))

    async def replied() -> bool:
        return bool(api.replies)

    await _run_until(database, tmp_path, api, replied)
    assert api.replies == [(4242, INVALID_LINK)]
    assert (await _chat_of(owner, contact))["telegram_chat_id"] is None


async def test_group_messages_are_ignored_but_confirmed(database: Database, tmp_path: Path) -> None:
    api = FakeTelegram(Update(400, -100123, "group", "/start algo"))

    async def confirmed() -> bool:
        return 401 in api.offsets

    await _run_until(database, tmp_path, api, confirmed)
    assert api.replies == []


async def test_a_failed_reply_does_not_undo_or_repeat_the_link(
    engine: AsyncEngine, owner: asyncpg.Connection, database: Database, tmp_path: Path
) -> None:
    contact, token = await _contact_with_link(engine, owner)
    api = FakeTelegram(Update(500, 4242, "private", f"/start {token}"), fail_replies=True)

    async def confirmed() -> bool:
        return 501 in api.offsets

    await _run_until(database, tmp_path, api, confirmed)
    assert (await _chat_of(owner, contact))["telegram_chat_id"] == 4242


async def test_without_a_bot_token_the_worker_only_beats(
    database: Database, tmp_path: Path
) -> None:
    settings = Settings(database_url=database.app_url, heartbeat_dir=tmp_path)
    assert settings.telegram_bot_token is None
    stop = asyncio.Event()
    worker = asyncio.create_task(run_telegram(settings, stop))
    beat = tmp_path / "telegram.alive"
    deadline = asyncio.get_running_loop().time() + 10
    while not beat.exists():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("sin latido")
        await asyncio.sleep(0.02)
    stop.set()
    await worker


def test_an_empty_token_in_the_environment_means_no_bot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIGIA_TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("VIGIA_TELEGRAM_BOT_USERNAME", "")
    settings = Settings(database_url="postgresql+asyncpg://x")
    assert (settings.telegram_bot_token, settings.telegram_bot_username) == (None, None)
