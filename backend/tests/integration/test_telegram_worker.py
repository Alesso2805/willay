"""VIG-21: the telegram worker links contacts, against real Postgres and a fake Telegram."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import Database
from tests.integration.factories import create_contact, create_graph
from tests.integration.telegram import FakeTelegram, run_telegram_until
from willay.alerts.application.policies import Actor
from willay.alerts.application.telegram_bot import Update
from willay.alerts.application.telegram_link import create_telegram_link
from willay.alerts.domain.telegram import HOW_TO_LINK, INVALID_LINK
from willay.alerts.infrastructure.sql_contact_links import SqlContactLinkRepository
from willay.shared.audit import SqlAuditLog
from willay.shared.clock import FakeClock, SystemClock
from willay.shared.config import Settings
from willay.shared.db import create_engine
from willay.workers.telegram import run_telegram

pytestmark = pytest.mark.integration


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
            Actor(graph.organization_id, graph.organization_id),  # the actor does not matter here
            contact,
            contacts=SqlContactLinkRepository(tx),
            audit=SqlAuditLog(tx),
            clock=FakeClock(now),
            bot_username="WillayAlertsBot",
        )
    return contact, link.url.rsplit("=", 1)[1]


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

    await run_telegram_until(database, tmp_path, api, linked_and_confirmed)

    row = await _chat_of(owner, contact)
    assert (row["telegram_chat_id"], row["telegram_link_token_hash"]) == (4242, None)
    [(chat, reply)] = api.replies
    assert chat == 4242
    assert reply.startswith("Listo, Lucho Quispe")
    assert api.offsets[0] is None  # first poll asks for every unacknowledged update
    audit = await owner.fetchval(
        "SELECT count(*) FROM core.audit_log WHERE entity_id = $1 AND action = 'telegram_linked'",
        contact,
    )
    assert audit == 1


@pytest.mark.parametrize(
    ("text", "reply"),
    [("/start " + "x" * 43, INVALID_LINK), ("/start", HOW_TO_LINK), ("hola", HOW_TO_LINK)],
    ids=["unknown-token", "no-token", "other-message"],
)
async def test_other_messages_get_a_helpful_reply(
    database: Database, tmp_path: Path, text: str, reply: str
) -> None:
    api = FakeTelegram(Update(200, 7, "private", text))

    async def replied() -> bool:
        return bool(api.replies)

    await run_telegram_until(database, tmp_path, api, replied)
    assert api.replies == [(7, reply)]


async def test_an_expired_link_does_not_link(
    engine: AsyncEngine, owner: asyncpg.Connection, database: Database, tmp_path: Path
) -> None:
    contact, token = await _contact_with_link(engine, owner, expired=True)
    api = FakeTelegram(Update(300, 4242, "private", f"/start {token}"))

    async def replied() -> bool:
        return bool(api.replies)

    await run_telegram_until(database, tmp_path, api, replied)
    assert api.replies == [(4242, INVALID_LINK)]
    assert (await _chat_of(owner, contact))["telegram_chat_id"] is None


async def test_group_messages_are_ignored_but_confirmed(database: Database, tmp_path: Path) -> None:
    api = FakeTelegram(Update(400, -100123, "group", "/start algo"))

    async def confirmed() -> bool:
        return 401 in api.offsets

    await run_telegram_until(database, tmp_path, api, confirmed)
    assert api.replies == []


async def test_a_failed_reply_does_not_undo_or_repeat_the_link(
    engine: AsyncEngine, owner: asyncpg.Connection, database: Database, tmp_path: Path
) -> None:
    contact, token = await _contact_with_link(engine, owner)
    api = FakeTelegram(Update(500, 4242, "private", f"/start {token}"), fail_replies=True)

    async def confirmed() -> bool:
        return 501 in api.offsets

    await run_telegram_until(database, tmp_path, api, confirmed)
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
            raise AssertionError("no heartbeat")
        await asyncio.sleep(0.02)
    stop.set()
    await worker


def test_an_empty_token_in_the_environment_means_no_bot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WILLAY_TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("WILLAY_TELEGRAM_BOT_USERNAME", "")
    settings = Settings(database_url="postgresql+asyncpg://x")
    assert (settings.telegram_bot_token, settings.telegram_bot_username) == (None, None)
