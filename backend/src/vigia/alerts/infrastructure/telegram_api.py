"""Cliente mínimo de la Bot API de Telegram (httpx2): lo que usan VIG-21 y VIG-22.

El token del bot va en la URL (`/bot<TOKEN>/<método>`), así que hay que cuidarlo:
- el logger de httpx2 registra cada petición con su URL a nivel INFO: queda en WARNING;
- los errores de httpx2 repiten la URL en su mensaje, y el worker registra la traza de
  los errores: se traducen a TelegramError SIN encadenar la excepción original (`from
  None`), solo con el método y el tipo de fallo.
"""

import logging
from typing import Any

import httpx2

from vigia.alerts.application.telegram_bot import TelegramError, Update

logging.getLogger("httpx2").setLevel(logging.WARNING)

# Solo lo que el bot atiende: mensajes (vincular) y clics en botones (confirmar, VIG-22).
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
        """Long polling: Telegram responde en cuanto hay algo o a los `timeout_s`. Pedir
        desde `offset` confirma las anteriores: Telegram no las vuelve a entregar."""
        payload: dict[str, Any] = {"timeout": timeout_s, "allowed_updates": ALLOWED_UPDATES}
        if offset is not None:
            payload["offset"] = offset
        result = await self._call("getUpdates", payload, timeout_s=timeout_s + 10)
        return [_update(raw) for raw in result]

    async def send_message(self, chat_id: int, text: str) -> None:
        await self._call("sendMessage", {"chat_id": chat_id, "text": text}, timeout_s=10)

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
    message = raw.get("message") or {}
    chat = message.get("chat") or {}
    return Update(
        update_id=raw["update_id"],
        chat_id=chat.get("id"),
        chat_type=chat.get("type"),
        text=message.get("text"),
    )
