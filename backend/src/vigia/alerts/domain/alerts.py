"""Alertas: a quién se notifica en cada nivel y por qué canal (SPEC: Alertas).

Cada nivel de la política notifica a grupos de contacto por un canal. Un contacto sin
ese canal (sin correo, o con Telegram sin vincular) no se puede notificar: su alerta se
registra como omitida (`skipped`) en lugar de desaparecer, para que la línea de tiempo
diga a quién no se pudo avisar.
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class Channel(StrEnum):
    EMAIL = "email"
    TELEGRAM = "telegram"


class AlertStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"
    ACKNOWLEDGED = "acknowledged"


@dataclass(frozen=True)
class Target:
    """Un contacto que un nivel debe notificar por un canal."""

    contact_id: UUID
    channel: Channel
    destination: str | None  # correo o chat_id de Telegram; None si no lo tiene

    @property
    def reachable(self) -> bool:
        return self.destination is not None and self.destination.strip() != ""

    @property
    def initial_status(self) -> AlertStatus:
        return AlertStatus.PENDING if self.reachable else AlertStatus.SKIPPED


SKIP_REASON = {
    Channel.EMAIL: "el contacto no tiene correo",
    Channel.TELEGRAM: "el contacto no vinculó Telegram",
}
