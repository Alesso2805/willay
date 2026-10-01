"""Telegram: linking a contact (VIG-21) and sending them alerts with a button (VIG-22).

Opening the `https://t.me/<bot>?start=<token>` link makes Telegram send `/start <token>`
to the bot, which thus learns the person's `chat_id` without anyone copying it by hand.
The 43-char base64url token fits the 64 chars `start` allows. It is valid for 7 days
because a community leader may take a while to open it.
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
    """The token of a `/start <token>` (or `/start@bot <token>`) message, or None if the
    message is not /start or carries no token."""
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
    """A Telegram alert: the same summary as the email, in plain text (no Markdown: a name
    with `*` or `_` would break the markup and Telegram would reject the message). The
    confirmation button is sent separately, with the token as `callback_data`."""
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
    """The note that replaces the button, or None to leave the message untouched: an
    unknown token or someone else's click must reveal nothing about the incident."""
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
    """The handled message: what the person saw, minus the escalation notice (no longer
    true), plus the note that replaces the button."""
    lines = [line for line in original.split("\n") if line != ESCALATION_NOTE]
    return "\n".join(lines) + f"\n\n{note}"
