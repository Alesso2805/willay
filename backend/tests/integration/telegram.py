"""Fake Telegram and an incident with a Telegram alert, for the VIG-21 and VIG-22 tests."""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import asyncpg
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import Database
from tests.integration.evaluation import Station
from tests.integration.factories import (
    Graph,
    add_level,
    create_contact,
    create_graph,
    create_group,
    create_rule,
    link_station,
)
from willay.alerts.application.telegram_bot import TelegramError, Update
from willay.shared.config import Settings
from willay.workers.telegram import run_telegram

GT_35_ONCE = {"operator": "gt", "value": 3.5, "consecutive": 1}
CHAT = 4242
EMAIL = "ana.telegram@x.test"


class FakeBot:
    """The sending side (dispatcher): fails the first `failures` times, or always."""

    def __init__(self, *, failures: int = 0, down: bool = False) -> None:
        self.failures, self.down = failures, down
        self.calls = 0
        self.sent: list[tuple[int, str, str]] = []
        self.buttons: list[str] = []

    async def send_alert(self, chat_id: int, text: str, callback_data: str, button: str) -> None:
        self.calls += 1
        if self.down or self.calls <= self.failures:
            raise TelegramError("sendMessage: 502 Bad Gateway")
        self.sent.append((chat_id, text, callback_data))
        self.buttons.append(button)


class FakeTelegram:
    """The receiving side (telegram worker): delivers updates until they are acknowledged."""

    def __init__(self, *updates: Update, fail_replies: bool = False) -> None:
        self.pending = list(updates)
        self.offsets: list[int | None] = []
        self.replies: list[tuple[int, str]] = []
        self.answers: list[tuple[str, str]] = []
        self.edits: list[tuple[int, int, str]] = []
        self.fail_replies = fail_replies

    async def get_updates(self, offset: int | None, timeout_s: int) -> list[Update]:
        self.offsets.append(offset)
        if offset is not None:  # asking from `offset` acknowledges the earlier ones
            self.pending = [u for u in self.pending if u.update_id >= offset]
        if not self.pending:
            await asyncio.sleep(0.02)  # long polling with nothing new
        return list(self.pending)

    async def send_message(self, chat_id: int, text: str) -> None:
        self._maybe_fail("sendMessage")
        self.replies.append((chat_id, text))

    async def answer_click(self, click_id: str, text: str) -> None:
        self._maybe_fail("answerCallbackQuery")
        self.answers.append((click_id, text))

    async def edit_message(self, chat_id: int, message_id: int, text: str) -> None:
        self._maybe_fail("editMessageText")
        self.edits.append((chat_id, message_id, text))

    def _maybe_fail(self, method: str) -> None:
        if self.fail_replies:
            raise TelegramError(f"{method}: 500 Internal Server Error")


async def run_telegram_until(
    database: Database, tmp_path: Path, api: FakeTelegram, done: Callable[[], Awaitable[bool]]
) -> None:
    settings = Settings(database_url=database.app_url, heartbeat_dir=tmp_path)
    stop = asyncio.Event()
    worker = asyncio.create_task(run_telegram(settings, stop, api=api, poll_timeout_s=1))
    try:
        deadline = asyncio.get_running_loop().time() + 10
        while not await done():
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("the worker did not finish in time")
            await asyncio.sleep(0.02)
    finally:
        stop.set()
        await worker


async def clear_pending_alerts(owner: asyncpg.Connection) -> None:
    """Shared database: a dispatcher must only see the alerts of the test that runs it."""
    await owner.execute("DELETE FROM ingest.evaluation_queue")
    await owner.execute("DELETE FROM core.alerts WHERE status = 'pending'")


async def telegram_incident(
    engine: AsyncEngine, owner: asyncpg.Connection, *, language: str | None = None
) -> Graph:
    """An incident whose level 1 notifies Ana by Telegram (linked) and by email; `language`
    is the one Ana chose for her alerts."""
    graph = await create_graph(owner)
    await link_station(owner, graph)
    await create_rule(owner, graph, "threshold", GT_35_ONCE, station_id=graph.station_id)
    ana = await create_contact(owner, graph, "Ana", email=EMAIL, telegram_chat_id=CHAT)
    await owner.execute("UPDATE core.contacts SET language = $1 WHERE id = $2", language, ana)
    group = await create_group(owner, graph, ana)
    await add_level(owner, graph, 1, (group, "telegram"), (group, "email"))
    await Station(engine, graph).send(3.6)
    return graph
