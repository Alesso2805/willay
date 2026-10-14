"""Telegram: linking a contact (VIG-21) and sending them alerts with a button (VIG-22).

Opening the `https://t.me/<bot>?start=<token>` link makes Telegram send `/start <token>`
to the bot, which thus learns the person's `chat_id` without anyone copying it by hand.
The 43-char base64url token fits the 64 chars `start` allows. It is valid for 7 days
because a community leader may take a while to open it.

Texts follow the contact's language (VIG-40). Someone the bot cannot tie to a contact (an
unknown sender, a stranger pressing a button) gets their Telegram app's language instead.
"""

from datetime import datetime, timedelta

from willay.alerts.domain.confirmation import ConfirmOutcome
from willay.alerts.domain.email import AlertMessage, local_time, summary
from willay.shared.i18n import translate
from willay.shared.languages import Language

LINK_TTL = timedelta(days=7)
MAX_START_PARAMETER = 64
MAX_CLICK_ANSWER = 200


def linked(name: str, organization: str, language: Language) -> str:
    return translate("alerts.telegram.linked", language, name=name, organization=organization)


def invalid_link(language: Language) -> str:
    return translate("alerts.telegram.invalid_link", language)


def how_to_link(language: Language) -> str:
    return translate("alerts.telegram.how_to_link", language)


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


def confirm_button(language: Language) -> str:
    return translate("alerts.telegram.button", language)


def escalation_note(language: Language) -> str:
    return translate("alerts.if_nobody_acknowledges", language)


def compose_alert_text(message: AlertMessage) -> str:
    """A Telegram alert: the same summary as the email, in plain text (no Markdown: a name
    with `*` or `_` would break the markup and Telegram would reject the message). The
    confirmation button is sent separately, with the token as `callback_data`."""
    language = message.language
    severity, cause, zone = (value for label, value in summary(message)[:3])
    details = [f"{label}: {value}" for label, value in summary(message)[3:]]
    title = translate("alerts.telegram.title", language, severity=severity, cause=cause, zone=zone)
    return "\n".join(
        [
            title,
            "",
            *details,
            "",
            escalation_note(language),
        ]
    )


def click_answer(outcome: ConfirmOutcome, language: Language) -> str:
    """The short notice Telegram shows whoever pressed the button."""
    return translate(f"alerts.telegram.click.{outcome}", language)


def closing_note(
    outcome: ConfirmOutcome,
    acknowledged_by: str | None,
    acknowledged_at: datetime | None,
    timezone: str,
    language: Language,
) -> str | None:
    """The note that replaces the button, or None to leave the message untouched: an
    unknown token or someone else's click must reveal nothing about the incident."""
    if outcome in (ConfirmOutcome.UNKNOWN, ConfirmOutcome.NOT_YOURS):
        return None
    if outcome is ConfirmOutcome.ALREADY_RESOLVED:
        return translate("alerts.telegram.note.resolved", language)
    if outcome is ConfirmOutcome.EXPIRED:
        return translate("alerts.telegram.note.expired", language)
    who = acknowledged_by or translate("alerts.telegram.note.someone_else", language)
    if acknowledged_at is None:
        return translate("alerts.telegram.note.acknowledged", language, who=who)
    time = local_time(acknowledged_at, timezone, language)
    return translate("alerts.telegram.note.acknowledged_at", language, who=who, time=time)


def closed_text(original: str, note: str) -> str:
    """The handled message: what the person saw, minus the escalation notice (no longer
    true), plus the note that replaces the button. The notice is looked for in every
    language: the contact may have changed theirs since the alert went out."""
    notices = {escalation_note(language) for language in Language}
    lines = [line for line in original.split("\n") if line not in notices]
    return "\n".join(lines) + f"\n\n{note}"
