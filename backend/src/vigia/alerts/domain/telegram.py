"""Telegram: vincular un contacto (VIG-21) y enviarle alertas con botón (VIG-22).

El admin genera un enlace `https://t.me/<bot>?start=<token>` y se lo comparte al contacto
por donde suela hablar con esa persona. Al abrirlo, Telegram le escribe al bot
`/start <token>`: así el bot conoce el `chat_id` de esa persona sin que nadie lo copie a
mano. El token (43 caracteres base64url) cabe en los 64 que admite `start` y solo usa
los caracteres que Telegram permite ahí. Vale 7 días: un líder comunal puede tardar en
abrirlo. Uno nuevo invalida el anterior.

Al pulsar el botón de una alerta, Telegram muestra un aviso breve (máximo 200 caracteres)
y el bot reemplaza el botón por una nota con quién confirmó y cuándo.
"""

from datetime import datetime, timedelta

from vigia.alerts.domain.confirmation import ConfirmOutcome
from vigia.alerts.domain.email import AlertMessage, local_time, summary

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


CONFIRM_BUTTON = "Confirmar que lo vi"
ESCALATION_NOTE = "Si nadie lo confirma, Vigía avisará al siguiente nivel."


def compose_alert_text(message: AlertMessage) -> str:
    """El mensaje de una alerta por Telegram: el mismo resumen del correo, en texto plano
    (sin Markdown: un nombre con `*` o `_` rompería el formato y Telegram lo rechazaría).
    El botón de confirmación va aparte, con el token como `callback_data`."""
    severity, cause, zone = (value for label, value in summary(message)[:3])
    details = [f"{label}: {value}" for label, value in summary(message)[3:]]
    return "\n".join(
        [
            f"Vigía · {severity}: {cause} en {zone}",
            "",
            *details,
            "",
            ESCALATION_NOTE,
            "Herramienta de apoyo: no reemplaza los avisos oficiales (INDECI, COER, SISMATE).",
        ]
    )


MAX_CLICK_ANSWER = 200

CLICK_ANSWER = {
    ConfirmOutcome.CONFIRMED: (
        "Gracias: confirmaste la alerta. Vigía no avisará al siguiente nivel."
    ),
    ConfirmOutcome.ALREADY_ACKNOWLEDGED: (
        "Gracias: quedó registrado que la viste. Otra persona ya había confirmado el incidente."
    ),
    ConfirmOutcome.ALREADY_RESOLVED: "Este incidente ya fue resuelto: no hace falta confirmarlo.",
    ConfirmOutcome.USED: "Ya confirmaste esta alerta.",
    ConfirmOutcome.EXPIRED: (
        "Este botón venció (vale 24 horas). Si el incidente sigue abierto, comunícate con el "
        "equipo de operaciones."
    ),
    ConfirmOutcome.UNKNOWN: "Esta alerta ya no es válida.",
    ConfirmOutcome.NOT_YOURS: "Solo quien recibió esta alerta puede confirmarla.",
}


def closing_note(
    outcome: ConfirmOutcome,
    acknowledged_by: str | None,
    acknowledged_at: datetime | None,
    timezone: str,
) -> str | None:
    """La nota que reemplaza al botón, o None si el mensaje no se toca: un token
    desconocido o un clic ajeno no dicen nada del incidente."""
    if outcome in (ConfirmOutcome.UNKNOWN, ConfirmOutcome.NOT_YOURS):
        return None
    if outcome is ConfirmOutcome.ALREADY_RESOLVED:
        return "Incidente resuelto: ya no hace falta confirmarlo."
    if outcome is ConfirmOutcome.EXPIRED:
        return "El botón venció (vale 24 horas)."
    who = acknowledged_by or "otra persona"
    when = f" el {local_time(acknowledged_at, timezone)}" if acknowledged_at is not None else ""
    return f"Confirmado por {who}{when}."


def closed_text(original: str, note: str) -> str:
    """El mensaje ya atendido: lo que la persona vio, sin el aviso de escalamiento (dejó de
    ser cierto) y con la nota que reemplaza al botón."""
    lines = [line for line in original.split("\n") if line != ESCALATION_NOTE]
    return "\n".join(lines) + f"\n\n{note}"
