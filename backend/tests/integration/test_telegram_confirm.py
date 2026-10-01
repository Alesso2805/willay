"""VIG-22 (part 2): confirming an incident with the Telegram alert button."""

from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import Database
from tests.integration.factories import Graph
from tests.integration.telegram import (
    CHAT,
    FakeBot,
    FakeTelegram,
    clear_pending_alerts,
    run_telegram_until,
    telegram_incident,
)
from willay.alerts.application.dispatch import TelegramDispatcher
from willay.alerts.application.telegram_bot import Click, Update
from willay.alerts.domain.confirmation import ConfirmOutcome
from willay.alerts.domain.telegram import CLICK_ANSWER, ESCALATION_NOTE
from willay.alerts.infrastructure.sql_dispatch import SqlDispatchQueue
from willay.shared.clock import SystemClock
from willay.shared.db import create_engine

pytestmark = pytest.mark.integration

MESSAGE_ID = 77


@pytest.fixture
async def engine(database: Database, owner: asyncpg.Connection) -> AsyncIterator[AsyncEngine]:
    await clear_pending_alerts(owner)
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


async def _alert_sent(engine: AsyncEngine, owner: asyncpg.Connection) -> tuple[Graph, str, str]:
    """The incident with its alert already sent: the text Ana saw and the button token."""
    graph = await telegram_incident(engine, owner)
    bot = FakeBot()
    await TelegramDispatcher(SqlDispatchQueue(engine), bot, SystemClock()).dispatch(10)
    [(_, text, token)] = bot.sent
    return graph, text, token


def _click(update_id: int, token: str, text: str, *, by: int = CHAT) -> Update:
    click = Click(f"c{update_id}", by, token, CHAT, MESSAGE_ID, text)
    return Update(update_id, click=click)


async def _state(owner: asyncpg.Connection, graph: Graph) -> asyncpg.Record:
    row = await owner.fetchrow(
        """
        SELECT i.status, c.full_name AS acknowledged_by, a.status AS alert_status,
               (SELECT count(*) FROM core.incident_events e
                WHERE e.incident_id = i.id AND e.event_type = 'acknowledged'
                  AND e.actor_type = 'contact') AS acknowledgements
        FROM core.incidents i
        JOIN core.alerts a ON a.incident_id = i.id AND a.channel = 'telegram'
        LEFT JOIN core.contacts c ON c.id = i.acknowledged_by_contact_id
        WHERE i.organization_id = $1
        """,
        graph.organization_id,
    )
    assert row is not None
    return row


async def test_the_recipient_confirms_with_the_button(
    engine: AsyncEngine, owner: asyncpg.Connection, database: Database, tmp_path: Path
) -> None:
    graph, text, token = await _alert_sent(engine, owner)
    # Double tap: the second click arrives with the token already used.
    api = FakeTelegram(_click(600, token, text), _click(601, token, text))

    async def both_confirmed() -> bool:
        return 602 in api.offsets

    await run_telegram_until(database, tmp_path, api, both_confirmed)

    state = await _state(owner, graph)
    assert (state["status"], state["acknowledged_by"], state["alert_status"]) == (
        "acknowledged",
        "Ana",
        "acknowledged",
    )
    assert state["acknowledgements"] == 1
    assert api.answers == [
        ("c600", CLICK_ANSWER[ConfirmOutcome.CONFIRMED]),
        ("c601", CLICK_ANSWER[ConfirmOutcome.USED]),
    ]
    chat, message_id, edited = api.edits[0]
    assert (chat, message_id) == (CHAT, MESSAGE_ID)
    kept, note = edited.rsplit("\n\n", 1)
    # What Ana saw is kept, except the escalation notice: it will no longer happen.
    assert ESCALATION_NOTE in text
    assert kept.split("\n") == [line for line in text.split("\n") if line != ESCALATION_NOTE]
    assert note.startswith("Confirmado por Ana el ")


async def test_someone_else_cannot_confirm_with_the_button(
    engine: AsyncEngine, owner: asyncpg.Connection, database: Database, tmp_path: Path
) -> None:
    graph, text, token = await _alert_sent(engine, owner)
    api = FakeTelegram(_click(700, token, text, by=999))

    async def answered() -> bool:
        return 701 in api.offsets

    await run_telegram_until(database, tmp_path, api, answered)

    state = await _state(owner, graph)
    assert (state["status"], state["alert_status"], state["acknowledgements"]) == (
        "open",
        "sent",
        0,
    )
    assert api.answers == [("c700", CLICK_ANSWER[ConfirmOutcome.NOT_YOURS])]
    assert api.edits == []


async def test_a_telegram_failure_does_not_undo_the_confirmation(
    engine: AsyncEngine, owner: asyncpg.Connection, database: Database, tmp_path: Path
) -> None:
    graph, text, token = await _alert_sent(engine, owner)
    api = FakeTelegram(_click(800, token, text), fail_replies=True)

    async def confirmed() -> bool:
        return 801 in api.offsets  # the update is acknowledged even though Telegram fails

    await run_telegram_until(database, tmp_path, api, confirmed)

    assert (await _state(owner, graph))["status"] == "acknowledged"
