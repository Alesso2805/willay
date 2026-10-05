"""VIG-22 (part 1): the dispatcher sends Telegram alerts with their button."""

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import Database
from tests.integration.factories import Graph
from tests.integration.telegram import (
    CHAT,
    EMAIL,
    FakeBot,
    clear_pending_alerts,
    telegram_incident,
)
from willay.alerts.application.dispatch import TelegramDispatcher
from willay.alerts.domain.email import EmailContent
from willay.alerts.infrastructure.sql_dispatch import SqlDispatchQueue
from willay.shared.clock import FakeClock, SystemClock
from willay.shared.config import Settings
from willay.shared.db import create_engine
from willay.workers.dispatcher import run_dispatcher

pytestmark = pytest.mark.integration


class FakeEmail:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, to: str, content: EmailContent) -> None:
        self.sent.append(to)


@pytest.fixture
async def engine(database: Database, owner: asyncpg.Connection) -> AsyncIterator[AsyncEngine]:
    await clear_pending_alerts(owner)
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


async def _alert(owner: asyncpg.Connection, graph: Graph, channel: str) -> asyncpg.Record:
    row = await owner.fetchrow(
        "SELECT a.id, a.status, a.attempts, a.ack_token_hash, a.last_error, a.destination"
        " FROM core.alerts a JOIN core.incidents i ON i.id = a.incident_id"
        " WHERE i.organization_id = $1 AND a.channel = $2",
        graph.organization_id,
        channel,
    )
    assert row is not None
    return row


async def _events(owner: asyncpg.Connection, alert_id: Any) -> list[dict[str, Any]]:
    rows = await owner.fetch(
        "SELECT event_type, payload FROM core.incident_events"
        " WHERE payload->>'alert_id' = $1 ORDER BY id",
        str(alert_id),
    )
    return [{"type": r["event_type"]} | json.loads(r["payload"]) for r in rows]


async def test_a_telegram_alert_is_sent_with_its_confirm_button(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    graph = await telegram_incident(engine, owner)
    bot = FakeBot()
    clock = FakeClock(SystemClock().now() + timedelta(seconds=1))
    await TelegramDispatcher(SqlDispatchQueue(engine), bot, clock).dispatch(10)

    [(chat, text, token)] = bot.sent
    assert chat == CHAT
    assert text.startswith("Willay · ADVERTENCIA: Valor fuera de límite en Zona")
    assert bot.buttons == ["Confirmar que lo vi"]
    assert len(token) == 43  # callback_data: within Telegram's 64-character limit
    alert = await _alert(owner, graph, "telegram")
    assert (alert["status"], alert["destination"]) == ("sent", str(CHAT))
    assert alert["ack_token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    [event] = await _events(owner, alert["id"])
    assert (event["type"], event["channel"]) == ("alert_sent", "telegram")


async def test_the_alert_and_its_button_are_in_the_language_of_the_contact(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    await telegram_incident(engine, owner, language="en")
    bot = FakeBot()
    clock = FakeClock(SystemClock().now() + timedelta(seconds=1))
    await TelegramDispatcher(SqlDispatchQueue(engine), bot, clock).dispatch(10)

    [(_, text, _)] = bot.sent
    assert text.startswith("Willay · WARNING: Value out of bounds in Zona")
    assert bot.buttons == ["Acknowledge: I saw it"]


async def test_telegram_failing_twice_delivers_on_the_third_attempt(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    graph = await telegram_incident(engine, owner)
    clock = FakeClock(SystemClock().now() + timedelta(seconds=1))
    dispatcher = TelegramDispatcher(SqlDispatchQueue(engine), FakeBot(failures=2), clock)
    for wait in (0, 5, 10):  # retries after 5 and 10 s
        clock.advance(timedelta(seconds=wait))
        await dispatcher.dispatch(10)

    alert = await _alert(owner, graph, "telegram")
    assert (alert["status"], alert["attempts"]) == ("sent", 3)
    events = await _events(owner, alert["id"])
    assert [(e["type"], e["attempt"], e["channel"]) for e in events] == [
        ("alert_failed", 1, "telegram"),
        ("alert_failed", 2, "telegram"),
        ("alert_sent", 3, "telegram"),
    ]
    assert events[0]["error"] == "sendMessage: 502 Bad Gateway"


async def test_a_telegram_outage_does_not_stop_the_email(
    engine: AsyncEngine, owner: asyncpg.Connection, database: Database, tmp_path: Path
) -> None:
    graph = await telegram_incident(engine, owner)
    smtp, bot = FakeEmail(), FakeBot(down=True)
    settings = Settings(database_url=database.app_url, heartbeat_dir=tmp_path)
    stop = asyncio.Event()
    worker = asyncio.create_task(
        run_dispatcher(settings, stop, sender=smtp, telegram=bot, poll_interval_s=0.05)
    )
    try:
        deadline = asyncio.get_running_loop().time() + 10
        while not (smtp.sent and bot.calls):
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("the dispatcher did not try both channels")
            await asyncio.sleep(0.05)
    finally:
        stop.set()
        await worker

    assert smtp.sent == [EMAIL]
    assert (await _alert(owner, graph, "email"))["status"] == "sent"
    telegram = await _alert(owner, graph, "telegram")
    assert (telegram["status"], telegram["last_error"]) == (
        "pending",
        "sendMessage: 502 Bad Gateway",
    )  # it will be retried
