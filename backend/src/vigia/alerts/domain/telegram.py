"""Vincular el Telegram de un contacto (VIG-21) con un enlace de un solo uso.

El admin genera un enlace `https://t.me/<bot>?start=<token>` y se lo comparte al contacto
por donde suela hablar con esa persona. Al abrirlo, Telegram le escribe al bot
`/start <token>`: así el bot conoce el `chat_id` de esa persona sin que nadie lo copie a
mano. El token (43 caracteres base64url) cabe en los 64 que admite `start` y solo usa
los caracteres que Telegram permite ahí. Vale 7 días: un líder comunal puede tardar en
abrirlo. Uno nuevo invalida el anterior.
"""

from datetime import timedelta

LINK_TTL = timedelta(days=7)
MAX_START_PARAMETER = 64

LINKED = "Listo, {name}: desde ahora recibirás aquí las alertas de Vigía de {organization}."
INVALID_LINK = (
    "Este enlace no es válido o ya venció. Pide uno nuevo a quien administra Vigía en tu "
    "organización."
)
HOW_TO_LINK = (
    "Este bot solo envía alertas de Vigía. Para recibirlas, abre el enlace que te compartió "
    "quien administra Vigía en tu organización."
)


def deep_link(bot_username: str, token: str) -> str:
    return f"https://t.me/{bot_username}?start={token}"


def start_parameter(text: str) -> str | None:
    """El token de un mensaje `/start <token>` (o `/start@bot <token>`), o None si el
    mensaje no es /start o no trae token."""
    command, _, argument = text.strip().partition(" ")
    if command.split("@", 1)[0] != "/start":
        return None
    token = argument.strip()
    return token if 0 < len(token) <= MAX_START_PARAMETER else None


def is_start(text: str) -> bool:
    return text.strip().split(" ", 1)[0].split("@", 1)[0] == "/start"
