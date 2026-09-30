"""El cliente de la Bot API contra un Telegram simulado (MockTransport, sin red)."""

import json
import traceback
from collections.abc import Callable

import httpx2
import pytest

from vigia.alerts.application.telegram_bot import TelegramError, Update
from vigia.alerts.infrastructure.telegram_api import TelegramBotApi

TOKEN = "123456:SECRETO-del-bot"


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
                    {"update_id": 8, "callback_query": {"id": "x"}},  # aún no se atiende
                ],
            },
        )

    updates = await _api(handler).get_updates(offset=7, timeout_s=20)

    assert updates == [Update(7, 42, "private", "/start abc"), Update(8)]
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
    # Como los errores reales de httpx2: el mensaje repite la URL, con el token dentro.
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
    ids=["sin-red", "token-rechazado"],
)
async def test_errors_never_carry_the_token(
    handler: Callable[[httpx2.Request], httpx2.Response], message: str
) -> None:
    with pytest.raises(TelegramError) as caught:
        await _api(handler).get_updates(offset=None, timeout_s=1)

    assert str(caught.value) == message
    # La traza completa (lo que registra el worker al fallar) tampoco lo lleva.
    trace = "".join(traceback.format_exception(caught.value))
    assert TOKEN not in trace


async def test_an_alert_carries_a_confirm_button_with_the_token() -> None:
    sent: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json={"ok": True, "result": {}})

    token = "t" * 43
    await _api(handler).send_alert(42, "Vigía · CRÍTICO", token)
    assert sent == [
        {
            "chat_id": 42,
            "text": "Vigía · CRÍTICO",
            "reply_markup": {
                "inline_keyboard": [[{"text": "Confirmar que lo vi", "callback_data": token}]]
            },
        }
    ]
