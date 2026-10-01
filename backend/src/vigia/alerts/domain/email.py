"""Alert email template (VIG-20): zone, severity, value, local time and confirmation link.

Plain text so it reads in any client, even a basic phone, without images or styles that
may be blocked. Times use the organization's timezone (the database stores UTC). The
footer states Vigía does not replace official warnings (SPEC: Explicit ethical risk).
"""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

SEVERITY_LABEL = {"info": "INFORMATIVO", "warning": "ADVERTENCIA", "critical": "CRÍTICO"}
# Spanish grammar differs per severity ("un incidente ADVERTENCIA" is not idiomatic).
SEVERITY_PHRASE = {
    "info": "un incidente INFORMATIVO",
    "warning": "un incidente de ADVERTENCIA",
    "critical": "un incidente CRÍTICO",
}
RULE_LABEL = {
    "threshold": "Valor fuera de límite",
    "rate_of_change": "Cambio brusco",
    "silence": "Estación sin reportar",
}


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


@dataclass(frozen=True)
class EmailContent:
    subject: str
    body: str


def summary(message: AlertMessage) -> list[tuple[str, str]]:
    """Incident data as (label, value) pairs, shared by the email and the confirmation page
    so both show the same thing."""
    fields = [
        ("Severidad", SEVERITY_LABEL.get(message.severity, message.severity.upper())),
        ("Causa", RULE_LABEL.get(message.rule_type, message.rule_type)),
        ("Zona", message.zone_name),
    ]
    if message.station_code:
        station = message.station_code + (
            f" · {message.station_name}" if message.station_name else ""
        )
        fields.append(("Estación", station))
    # For silence the value is the last known reading, not one that triggered the rule.
    fields.append(("Último" if message.rule_type == "silence" else "Valor", _value(message)))
    fields.append(("Abierto", local_time(message.opened_at, message.timezone)))
    return fields


def local_time(instant: datetime, timezone: str) -> str:
    return f"{instant.astimezone(ZoneInfo(timezone)):%d/%m/%Y %H:%M} ({timezone})"


def compose_email(message: AlertMessage, confirm_url: str) -> EmailContent:
    severity = SEVERITY_LABEL.get(message.severity, message.severity.upper())
    cause = RULE_LABEL.get(message.rule_type, message.rule_type)
    where = message.zone_name + (f" ({message.station_code})" if message.station_code else "")
    # Severity and zone are already in the opening sentence; the rest go in aligned columns.
    details = [
        f"  {label + ':':<11}{value}"
        for label, value in summary(message)
        if label not in ("Severidad", "Zona")
    ]
    lines = [
        f"Hola {message.contact_name}:",
        "",
        f"Vigía abrió {_phrase(message.severity)} en la zona {message.zone_name}.",
        "",
        *details,
        "",
        "Confirma que lo viste en este enlace (vale 24 horas):",
        confirm_url,
        "",
        "Si nadie lo confirma, Vigía avisará al siguiente nivel.",
        "",
        "--",
        f"Vigía · {message.organization_name}",
        "Herramienta de apoyo para operadores: no reemplaza los avisos oficiales",
        "(INDECI, COER, SISMATE).",
    ]
    return EmailContent(subject=f"[Vigía] {severity} · {cause} en {where}", body="\n".join(lines))


def _phrase(severity: str) -> str:
    return SEVERITY_PHRASE.get(severity, f"un incidente {severity.upper()}")


def _value(message: AlertMessage) -> str:
    if message.trigger_value is None:
        return "sin dato"
    unit = f" {message.unit}" if message.unit else ""
    return f"{message.trigger_value:g}{unit}"
