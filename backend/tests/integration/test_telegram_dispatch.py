"""VIG-22 (parte 1): el dispatcher envía las alertas de Telegram con su botón."""

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
from vigia.alerts.application.dispatch import TelegramDispatcher
from vigia.alerts.application.telegram_bot import TelegramError
from vigia.alerts.domain.email import EmailContent
from vigia.alerts.infrastructure.sql_dispatch import SqlDispatchQueue
from vigia.shared.clock import FakeClock, SystemClock
from vigia.shared.config import Settings
from vigia.shared.db import create_engine
from vigia.workers.dispatcher import run_dispatcher

pytestmark = pytest.mark.integration

GT_35_ONCE = {"operator": "gt", "value": 3.5, "consecutive": 1}
CHAT = 4242
EMAIL = "ana.telegram@x.test"


class FakeBot:
    def __init__(self, *, failures: int = 0, down: bool = False) -> None:
        self.failures, self.down = failures, down
        self.calls = 0
        self.sent: list[tuple[int, str, str]] = []

    async def send_alert(self, chat_id: int, text: str, callback_data: str) -> None:
        self.calls += 1
        if self.down or self.calls <= self.failures:
            raise TelegramError("sendMessage: 502 Bad Gateway")
        self.sent.append((chat_id, text, callback_data))


class FakeEmail:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, to: str, content: EmailContent) -> None:
        self.sent.append(to)


@pytest.fixture
async def engine(database: Database, owner: asyncpg.Connection) -> AsyncIterator[AsyncEngine]:
    # Base compartida: el dispatcher solo debe ver las alertas de este test.
    await owner.execute("DELETE FROM ingest.evaluation_queue")
    await owner.execute("DELETE FROM core.alerts WHERE status = 'pending'")
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


async def _incident(engine: AsyncEngine, owner: asyncpg.Connection) -> Graph:
    """Un incidente cuyo nivel 1 avisa a Ana por Telegram (vinculado) y por correo."""
    graph = await create_graph(owner)
    await link_station(owner, graph)
    await create_rule(owner, graph, "threshold", GT_35_ONCE, station_id=graph.station_id)
    ana = await create_contact(owner, graph, "Ana", email=EMAIL, telegram_chat_id=CHAT)
    group = await create_group(owner, graph, ana)
    await add_level(owner, graph, 1, (group, "telegram"), (group, "email"))
    await Station(engine, graph).send(3.6)
    return graph


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
    graph = await _incident(engine, owner)
    bot = FakeBot()
    clock = FakeClock(SystemClock().now() + timedelta(seconds=1))
    await TelegramDispatcher(SqlDispatchQueue(engine), bot, clock).dispatch(10)

    [(chat, text, token)] = bot.sent
    assert chat == CHAT
    assert text.startswith("Vigía · ADVERTENCIA: Valor fuera de límite en Zona")
    assert len(token) == 43  # callback_data: dentro de los 64 de Telegram
    alert = await _alert(owner, graph, "telegram")
    assert (alert["status"], alert["destination"]) == ("sent", str(CHAT))
    assert alert["ack_token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    [event] = await _events(owner, alert["id"])
    assert (event["type"], event["channel"]) == ("alert_sent", "telegram")


async def test_telegram_failing_twice_delivers_on_the_third_attempt(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    graph = await _incident(engine, owner)
    clock = FakeClock(SystemClock().now() + timedelta(seconds=1))
    dispatcher = TelegramDispatcher(SqlDispatchQueue(engine), FakeBot(failures=2), clock)
    for wait in (0, 5, 10):  # reintentos a los 5 y a los 10 s
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
    graph = await _incident(engine, owner)
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
                raise AssertionError("el dispatcher no intentó ambos canales")
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
    )  # se reintentará
