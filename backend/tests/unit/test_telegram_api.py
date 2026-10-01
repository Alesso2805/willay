"""The Bot API client against a simulated Telegram (MockTransport, no network)."""

import json
import traceback
from collections.abc import Callable

import httpx2
import pytest

from willay.alerts.application.telegram_bot import Click, TelegramError, Update
from willay.alerts.infrastructure.telegram_api import TelegramBotApi

TOKEN = "123456:SECRET-bot-token"


def _api(handler: Callable[[httpx2.Request], httpx2.Response]) -> TelegramBotApi:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return TelegramBotApi(TOKEN, base_url="https://telegram.test", client=client)


async def test_updates_are_long_polled_from_the_offset() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200,
            json={
                "ok": True,
                "result": [
                    {
                        "update_id": 7,
                        "message": {"chat": {"id": 42, "type": "private"}, "text": "/start abc"},
                    },
                    {
                        "update_id": 8,
                        "callback_query": {
                            "id": "c8",
                            "from": {"id": 42},
                            "data": "t" * 43,
                            "message": {
                                "message_id": 5,
                                "chat": {"id": 42, "type": "private"},
                                "text": "Willay · CRÍTICO",
                            },
                        },
                    },
                    # A message older than 48 h: Telegram no longer sends its text.
                    {
                        "update_id": 9,
                        "callback_query": {
                            "id": "c9",
                            "from": {"id": 42},
                            "message": {"message_id": 3, "chat": {"id": 42}, "date": 0},
                        },
                    },
                    {"update_id": 10, "callback_query": {"id": "c10"}},  # unreadable
                ],
            },
        )

    updates = await _api(handler).get_updates(offset=7, timeout_s=20)

    assert updates == [
        Update(7, 42, "private", "/start abc"),
        Update(8, click=Click("c8", 42, "t" * 43, 42, 5, "Willay · CRÍTICO")),
        Update(9, click=Click("c9", 42, None, 42, 3, None)),
        Update(10),  # acknowledged and dropped so it does not block the next ones
    ]
    [request] = seen
    assert request.url.path == f"/bot{TOKEN}/getUpdates"
    assert json.loads(request.content) == {
        "timeout": 20,
        "allowed_updates": ["message", "callback_query"],
        "offset": 7,
    }


async def test_a_message_is_sent_to_the_chat() -> None:
    sent: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json={"ok": True, "result": {}})

    await _api(handler).send_message(42, "Listo")
    assert sent == [{"chat_id": 42, "text": "Listo"}]


def _unreachable(request: httpx2.Request) -> httpx2.Response:
    # Like real httpx2 errors: the message repeats the URL, token included.
    raise httpx2.ConnectError(f"cannot reach {request.url}", request=request)


@pytest.mark.parametrize(
    ("handler", "message"),
    [
        (_unreachable, "getUpdates: ConnectError"),
        (
            lambda request: httpx2.Response(
                401, json={"ok": False, "error_code": 401, "description": "Unauthorized"}
            ),
            "getUpdates: 401 Unauthorized",
        ),
    ],
    ids=["no-network", "token-rejected"],
)
async def test_errors_never_carry_the_token(
    handler: Callable[[httpx2.Request], httpx2.Response], message: str
) -> None:
    with pytest.raises(TelegramError) as caught:
        await _api(handler).get_updates(offset=None, timeout_s=1)

    assert str(caught.value) == message
    # Nor does the full traceback, which is what the worker logs on failure.
    trace = "".join(traceback.format_exception(caught.value))
    assert TOKEN not in trace


async def test_an_alert_carries_a_confirm_button_with_the_token() -> None:
    sent: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json={"ok": True, "result": {}})

    token = "t" * 43
    await _api(handler).send_alert(42, "Willay · CRÍTICO", token)
    assert sent == [
        {
            "chat_id": 42,
            "text": "Willay · CRÍTICO",
            "reply_markup": {
                "inline_keyboard": [[{"text": "Confirmar que lo vi", "callback_data": token}]]
            },
        }
    ]


async def test_a_click_is_answered_and_the_button_removed() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append((request.url.path.rsplit("/", 1)[1], json.loads(request.content)))
        return httpx2.Response(200, json={"ok": True, "result": True})

    api = _api(handler)
    await api.answer_click("c8", "Gracias")
    await api.edit_message(42, 5, "Willay · CRÍTICO\n\nConfirmado por Ana")
    assert calls == [
        ("answerCallbackQuery", {"callback_query_id": "c8", "text": "Gracias"}),
        (
            "editMessageText",
            {
                "chat_id": 42,
                "message_id": 5,
                "text": "Willay · CRÍTICO\n\nConfirmado por Ana",
                "reply_markup": {"inline_keyboard": []},  # no button
            },
        ),
    ]
