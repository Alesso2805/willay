"""Minimal Telegram Bot API client (httpx2): what linking and confirming use.

The bot token is part of the URL (`/bot<TOKEN>/<method>`), so it must not leak:
- httpx2 logs every request URL at INFO, so its logger is raised to WARNING;
- httpx2 errors repeat the URL and the worker logs tracebacks, so they become a
  TelegramError WITHOUT chaining (`from None`), carrying only the method and error type.
"""

import logging
from typing import Any

import httpx2

from willay.alerts.application.telegram_bot import Click, TelegramError, Update

logging.getLogger("httpx2").setLevel(logging.WARNING)

# Only what the bot handles: messages (linking) and button clicks (confirming).
ALLOWED_UPDATES = ["message", "callback_query"]


class TelegramBotApi:
    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://api.telegram.org",
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/bot{token}"
        self._client = client or httpx2.AsyncClient()

    async def get_updates(self, offset: int | None, timeout_s: int) -> list[Update]:
        """Long polling: Telegram answers as soon as there is something or after
        `timeout_s`. Asking from `offset` acknowledges earlier updates: they are not resent."""
        payload: dict[str, Any] = {"timeout": timeout_s, "allowed_updates": ALLOWED_UPDATES}
        if offset is not None:
            payload["offset"] = offset
        result = await self._call("getUpdates", payload, timeout_s=timeout_s + 10)
        return [_update(raw) for raw in result]

    async def send_message(self, chat_id: int, text: str) -> None:
        await self._call("sendMessage", {"chat_id": chat_id, "text": text}, timeout_s=10)

    async def send_alert(self, chat_id: int, text: str, callback_data: str, button: str) -> None:
        """Message with an inline button: the click reaches the bot as a `callback_query`."""
        keyboard_button = {"text": button, "callback_data": callback_data}
        payload = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": {"inline_keyboard": [[keyboard_button]]},
        }
        await self._call("sendMessage", payload, timeout_s=10)

    async def answer_click(self, click_id: str, text: str) -> None:
        """The short notice Telegram shows on click; without an answer the button keeps
        spinning."""
        payload = {"callback_query_id": click_id, "text": text}
        await self._call("answerCallbackQuery", payload, timeout_s=10)

    async def edit_message(self, chat_id: int, message_id: int, text: str) -> None:
        """An empty keyboard removes the button: there is nothing left to confirm."""
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "reply_markup": {"inline_keyboard": []},
        }
        await self._call("editMessageText", payload, timeout_s=10)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, payload: dict[str, Any], *, timeout_s: float) -> Any:
        try:
            response = await self._client.post(
                f"{self._url}/{method}", json=payload, timeout=timeout_s
            )
            body = response.json()
        except (httpx2.HTTPError, ValueError) as exc:
            raise TelegramError(f"{method}: {type(exc).__name__}") from None
        if not isinstance(body, dict) or not body.get("ok"):
            error = body.get("error_code") if isinstance(body, dict) else None
            description = body.get("description") if isinstance(body, dict) else None
            raise TelegramError(f"{method}: {error} {description}") from None
        return body["result"]


def _update(raw: dict[str, Any]) -> Update:
    callback = raw.get("callback_query")
    if callback is not None:
        return Update(update_id=raw["update_id"], click=_click(callback))
    message = raw.get("message") or {}
    chat = message.get("chat") or {}
    return Update(
        update_id=raw["update_id"],
        chat_id=chat.get("id"),
        chat_type=chat.get("type"),
        text=message.get("text"),
        language_code=(message.get("from") or {}).get("language_code"),
    )


def _click(callback: dict[str, Any]) -> Click | None:
    """None if the essentials are missing: an unreadable update is acknowledged and
    dropped, never blocking the ones after it."""
    sender = callback.get("from") or {}
    if "id" not in callback or "id" not in sender:
        return None
    # A message older than 48 h arrives "inaccessible": chat and message_id but no text.
    message = callback.get("message") or {}
    return Click(
        id=callback["id"],
        clicker_id=sender["id"],
        token=callback.get("data"),
        chat_id=(message.get("chat") or {}).get("id"),
        message_id=message.get("message_id"),
        message_text=message.get("text"),
        language_code=sender.get("language_code"),
    )
