"""Confirmar una alerta con su token (VIG-23): uso único y 24 h de validez.

Confirmar cualquier alerta confirma el incidente (SPEC). Si otro se adelantó, la alerta
queda registrada como vista sin cambiar quién lo confirmó; si el incidente ya se
resolvió, no se cambia nada. Ninguno de los dos casos es un error de quien confirma.
"""

from datetime import datetime
from enum import StrEnum


class ConfirmOutcome(StrEnum):
    CONFIRMED = "confirmed"  # el incidente pasó a confirmado por este contacto
    ALREADY_ACKNOWLEDGED = "already_acknowledged"  # otro se adelantó; la alerta quedó vista
    ALREADY_RESOLVED = "already_resolved"  # nada que hacer
    UNKNOWN = "unknown"  # ningún token coincide
    EXPIRED = "expired"
    USED = "used"
    NOT_YOURS = "not_yours"  # el botón de Telegram lo pulsó otra persona (VIG-22)


def token_problem(
    expires_at: datetime | None, used_at: datetime | None, now: datetime
) -> ConfirmOutcome | None:
    """Por qué el token ya no sirve, o None si todavía vale."""
    if used_at is not None:
        return ConfirmOutcome.USED
    if expires_at is None or now >= expires_at:
        return ConfirmOutcome.EXPIRED
    return None
