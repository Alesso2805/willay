"""VIG-30: without Telegram, the demo acknowledges as a level-2 contact from their email."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx2
import pytest

from willay.demo.mailbox import (
    READING_DELAY_S,
    EmailAcknowledger,
    MailpitMailbox,
    Recipient,
    confirm_token,
)
from willay.demo.story import AckMode, choose_mode
from willay.shared.clock import FakeClock

TOKEN = "q" * 43
ROSA = Recipient("Rosa Brigada", "brigada@rimac.willay.test")


def _email(token: str) -> str:
    return f"Confirmar que lo vi: http://localhost:8000/confirmar/{token}\n\nWillay"


class FakeMailbox:
    def __init__(self) -> None:
        self.messages: dict[str, str] = {}

    async def messages_to(self, address: str) -> list[str]:
        assert address == ROSA.email
        return list(reversed(self.messages))

    async def text(self, message_id: str) -> str:
        return self.messages[message_id]


class Harness:
    def __init__(self, alerts: dict[str, tuple[UUID, int]]) -> None:
        self.clock = FakeClock(datetime(2026, 10, 4, 5, 52, tzinfo=UTC))
        self.mailbox = FakeMailbox()
        self.confirmed: list[str] = []
        self.acknowledger = EmailAcknowledger(
            ROSA, self.mailbox, self._lookup, self._confirm, self.clock
        )
        self._alerts = alerts

    async def _lookup(self, token: str) -> tuple[UUID, int] | None:
        return self._alerts.get(token)

    async def _confirm(self, token: str) -> int:
        self.confirmed.append(token)
        return 200


async def test_it_presses_confirm_once_a_few_seconds_after_the_level_2_email_arrives() -> None:
    incident = uuid4()
    harness = Harness({TOKEN: (incident, 2)})
    harness.mailbox.messages["m1"] = _email(TOKEN)

    assert await harness.acknowledger.step({incident}) == []  # it has just arrived
    harness.clock.advance(timedelta(seconds=READING_DELAY_S))
    assert await harness.acknowledger.step({incident}) == [
        (incident, "the demo presses Confirm in Rosa Brigada's email")
    ]
    assert await harness.acknowledger.step({incident}) == []  # once
    assert harness.confirmed == [TOKEN]


async def test_other_emails_are_never_acted_on() -> None:
    story, elsewhere = uuid4(), uuid4()
    level_1, other_incident = "a" * 43, "b" * 43
    harness = Harness({level_1: (story, 1), other_incident: (elsewhere, 2)})
    harness.mailbox.messages = {
        "old": _email("c" * 43),  # a previous run's: its alert no longer exists
        "level-1": _email(level_1),
        "other": _email(other_incident),
        "no-link": "Hola",
    }
    harness.clock.advance(timedelta(minutes=5))
    await harness.acknowledger.step({story})
    harness.clock.advance(timedelta(minutes=5))
    assert await harness.acknowledger.step({story}) == []
    assert harness.confirmed == []


def test_the_token_comes_from_the_email_link() -> None:
    assert confirm_token(_email(TOKEN)) == TOKEN
    assert confirm_token("http://localhost:8000/confirmar/") is None


async def test_mailpit_is_searched_by_recipient_and_read_by_message() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/api/v1/search":
            assert request.url.params["query"] == f'to:"{ROSA.email}"'
            return httpx2.Response(200, json={"messages": [{"ID": "m2"}, {"ID": "m1"}]})
        assert request.url.path == "/api/v1/message/m2"
        return httpx2.Response(200, content=json.dumps({"Text": _email(TOKEN)}))

    transport = httpx2.MockTransport(handler)
    async with httpx2.AsyncClient(transport=transport, base_url="http://mailpit:8025") as client:
        mailbox = MailpitMailbox(client)
        assert await mailbox.messages_to(ROSA.email) == ["m2", "m1"]
        assert confirm_token(await mailbox.text("m2")) == TOKEN


@pytest.mark.parametrize(
    ("requested", "telegram", "email", "chosen"),
    [
        (AckMode.AUTO, ["Rosa Brigada"], ["Rosa Brigada"], AckMode.TELEGRAM),
        (AckMode.AUTO, [], ["Rosa Brigada"], AckMode.EMAIL),
        (AckMode.EMAIL, ["Rosa Brigada"], ["Rosa Brigada"], AckMode.EMAIL),
        (AckMode.TELEGRAM, ["Rosa Brigada"], [], AckMode.TELEGRAM),
    ],
)
def test_level_2_acknowledges_from_telegram_when_someone_has_it_linked(
    requested: AckMode, telegram: list[str], email: list[str], chosen: AckMode
) -> None:
    assert choose_mode(requested, telegram, email) is chosen


def test_it_explains_when_nobody_could_acknowledge_that_way() -> None:
    assert "Generar enlace de Telegram" in str(choose_mode(AckMode.TELEGRAM, [], ["Rosa"]))
    assert "nobody could acknowledge" in str(choose_mode(AckMode.AUTO, [], []))
    assert "gets email" in str(choose_mode(AckMode.EMAIL, ["Rosa"], []))


def test_a_reason_is_told_apart_from_a_mode_by_its_type_not_by_being_a_str() -> None:
    chosen = choose_mode(AckMode.EMAIL, [], ["Rosa"])
    reason = choose_mode(AckMode.EMAIL, ["Rosa"], [])
    assert isinstance(chosen, str)
    assert isinstance(chosen, AckMode)
    assert not isinstance(reason, AckMode)
