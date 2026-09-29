"""Plantilla del correo de alerta (VIG-20): zona, severidad, valor, hora local y enlace.

Texto plano: se lee en cualquier cliente, también en un teléfono básico, y no depende de
imágenes ni estilos que el cliente puede bloquear. La hora va en la zona horaria de la
organización (en la base todo es UTC). El pie recuerda que Vigía es una herramienta de
apoyo y no reemplaza los avisos oficiales (SPEC: Riesgo ético).
"""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

SEVERITY_LABEL = {"info": "INFORMATIVO", "warning": "ADVERTENCIA", "critical": "CRÍTICO"}
RULE_LABEL = {
    "threshold": "Valor fuera de límite",
    "rate_of_change": "Cambio brusco",
    "silence": "Estación sin reportar",
}


@dataclass(frozen=True)
class AlertMessage:
    """Lo que el correo necesita saber del incidente y de su destinatario."""

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


def compose_email(message: AlertMessage, confirm_url: str) -> EmailContent:
    severity = SEVERITY_LABEL.get(message.severity, message.severity.upper())
    cause = RULE_LABEL.get(message.rule_type, message.rule_type)
    where = message.zone_name + (f" ({message.station_code})" if message.station_code else "")
    local = message.opened_at.astimezone(ZoneInfo(message.timezone))

    lines = [
        f"Hola {message.contact_name}:",
        "",
        f"Vigía abrió un incidente {severity} en la zona {message.zone_name}.",
        "",
        f"  Causa:     {cause}",
    ]
    if message.station_code:
        station = message.station_code + (
            f" · {message.station_name}" if message.station_name else ""
        )
        lines.append(f"  Estación:  {station}")
    lines += [
        f"  {_value_label(message)}{_value(message)}",
        f"  Abierto:   {local:%d/%m/%Y %H:%M} ({message.timezone})",
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


def _value_label(message: AlertMessage) -> str:
    # En silencio el valor es el último conocido, no el que disparó la regla.
    return "Último:    " if message.rule_type == "silence" else "Valor:     "


def _value(message: AlertMessage) -> str:
    if message.trigger_value is None:
        return "sin dato"
    unit = f" {message.unit}" if message.unit else ""
    return f"{message.trigger_value:g}{unit}"
