"""Alert email template (VIG-20): zone, severity, value, local time and confirmation link.

Plain text so it reads in any client, even a basic phone, without images or styles that
may be blocked. Times use the organization's timezone (the database stores UTC).
Written in the contact's language (VIG-40); the texts live in the backend's catalogs.
"""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from willay.shared.errors import Term
from willay.shared.i18n import translate
from willay.shared.languages import Language

# English month names are spelled out here rather than taken from strftime("%b"), which
# depends on the process locale.
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class AlertMessage:
    """What the message needs to know about the incident and its recipient."""

    contact_name: str
    organization_name: str
    timezone: str
    zone_name: str
    severity: str
    rule_type: str
    station_code: str | None
    station_name: str | None
    unit: str | None
    trigger_value: float | None
    opened_at: datetime
    level_order: int
    language: Language  # the contact's, or else the organization's


@dataclass(frozen=True)
class EmailContent:
    subject: str
    body: str


def _fields(message: AlertMessage) -> list[tuple[str, str]]:
    """Incident data as (field, value) pairs: what the email, the Telegram message and the
    confirmation page all show."""
    language = message.language
    fields = [
        ("severity", translate(f"alerts.severity.{message.severity}", language)),
        ("cause", translate(f"alerts.cause.{message.rule_type}", language)),
        ("zone", message.zone_name),
    ]
    if message.station_code:
        station = message.station_code + (
            f" · {message.station_name}" if message.station_name else ""
        )
        fields.append(("station", station))
    # For silence the value is the last known reading, not one that triggered the rule.
    fields.append(("last_value" if message.rule_type == "silence" else "value", _value(message)))
    fields.append(("opened", local_time(message.opened_at, message.timezone, language)))
    return fields


def summary(message: AlertMessage) -> list[tuple[str, str]]:
    """Incident data as translated (label, value) pairs, for the confirmation page and the
    Telegram message; the email lays out the same fields, so all three show the same
    thing."""
    return [
        (translate(f"alerts.field.{field}", message.language), value)
        for field, value in _fields(message)
    ]


def local_time(instant: datetime, timezone: str, language: Language) -> str:
    """Spanish writes "20/11/2026 09:00 (America/Lima)"; English "Nov 20, 2026, 09:00
    (America/Lima)", whose month name avoids reading 04/10 as April 10. As the dashboard."""
    local = instant.astimezone(ZoneInfo(timezone))
    if language is Language.EN:
        text = f"{_MONTHS[local.month - 1]} {local.day}, {local.year}, {local:%H:%M}"
    else:
        text = f"{local:%d/%m/%Y %H:%M}"
    return f"{text} ({timezone})"


def compose_email(message: AlertMessage, confirm_url: str) -> EmailContent:
    language = message.language
    fields = dict(_fields(message))
    where = message.zone_name + (f" ({message.station_code})" if message.station_code else "")
    # Severity and zone are already in the opening sentence; the rest go in aligned columns.
    details = [
        (translate(f"alerts.field.{field}", language) + ":", value)
        for field, value in _fields(message)
        if field not in ("severity", "zone")
    ]
    width = max(len(label) for label, _ in details) + 2
    lines = [
        translate("alerts.email.greeting", language, name=message.contact_name),
        "",
        translate(
            "alerts.email.opened",
            language,
            incident=Term(f"alerts.incident_of_severity.{message.severity}"),
            zone=message.zone_name,
        ),
        "",
        *(f"  {label:<{width}}{value}" for label, value in details),
        "",
        translate("alerts.email.confirm", language),
        confirm_url,
        "",
        translate("alerts.if_nobody_acknowledges", language),
        "",
        "--",
        f"Willay · {message.organization_name}",
    ]
    subject = translate(
        "alerts.email.subject",
        language,
        severity=fields["severity"],
        cause=fields["cause"],
        place=where,
    )
    return EmailContent(subject=subject, body="\n".join(lines))


def _value(message: AlertMessage) -> str:
    if message.trigger_value is None:
        return translate("alerts.no_value", message.language)
    unit = f" {message.unit}" if message.unit else ""
    return f"{message.trigger_value:g}{unit}"
