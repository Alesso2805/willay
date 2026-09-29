"""Ciclo de vida de un incidente (VIG-19): open → acknowledged → resolved.

- Confirmar (acknowledge) solo desde `open`: registra quién lo vio y, con las alertas
  (VIG-23/24), detiene el escalamiento.
- Resolver desde `open` o `acknowledged`, como resuelto o falsa alarma. Resolver sin
  confirmar antes es válido (decisión de producto): una falsa alarma evidente se cierra
  en un paso, y el evento `resolved` registra quién lo hizo.
- `resolved` es final: cualquier otra transición es inválida (la API responde 409).
"""

from enum import StrEnum


class IncidentStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class Resolution(StrEnum):
    RESOLVED = "resolved"
    FALSE_ALARM = "false_alarm"


class Transition(StrEnum):
    ACKNOWLEDGE = "acknowledge"
    RESOLVE = "resolve"


ALLOWED_FROM: dict[Transition, frozenset[IncidentStatus]] = {
    Transition.ACKNOWLEDGE: frozenset({IncidentStatus.OPEN}),
    Transition.RESOLVE: frozenset({IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED}),
}


class InvalidTransitionError(Exception):
    def __init__(self, transition: Transition, current: IncidentStatus) -> None:
        super().__init__(f"no se puede {transition} un incidente en estado {current}")
        self.transition = transition
        self.current = current


def ensure_allowed(transition: Transition, current: IncidentStatus) -> None:
    if current not in ALLOWED_FROM[transition]:
        raise InvalidTransitionError(transition, current)
