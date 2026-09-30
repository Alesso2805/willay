"""Escalamiento por niveles (VIG-24): cuándo un incidente sube de nivel o agota la política.

El nivel actual vence si:
- pasaron `wait_s` desde que se le avisó (`level_started_at`) sin que nadie confirmara;
- no pudo avisar a nadie: todas sus alertas quedaron omitidas por canal faltante (SPEC:
  "un nivel sin ningún envío escala de inmediato"), también el nivel 1 al abrirse;
- ya no existe en la política: un admin lo quitó mientras el incidente escalaba (los
  cambios aplican a los incidentes en curso).

Al vencer, sube al siguiente nivel de la política; si no hay otro, la política se agotó.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class Step(StrEnum):
    WAIT = "wait"
    ESCALATE = "escalate"
    EXHAUST = "exhaust"


@dataclass(frozen=True)
class Decision:
    step: Step
    reason: str | None = None  # por qué venció el nivel; va en el evento


@dataclass(frozen=True)
class LevelState:
    """El nivel actual de un incidente abierto, visto contra la política vigente."""

    current_level: int
    level_started_at: datetime
    wait_s: int | None  # None: el nivel ya no existe en la política
    next_level: int | None  # el siguiente nivel de la política, si hay
    nobody_alerted: bool  # todas las alertas del nivel quedaron omitidas


def decide(state: LevelState, now: datetime) -> Decision:
    level = state.current_level
    if state.wait_s is None:
        reason = f"el nivel {level} ya no existe en la política"
    elif state.nobody_alerted:
        reason = f"el nivel {level} no pudo avisar a nadie"
    elif now - state.level_started_at >= timedelta(seconds=state.wait_s):
        reason = f"nadie confirmó en {state.wait_s} s"
    else:
        return Decision(Step.WAIT)
    step = Step.ESCALATE if state.next_level is not None else Step.EXHAUST
    return Decision(step, reason)
