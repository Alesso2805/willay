"""Señales simuladas de estaciones: puras y reproducibles con una semilla.

El valor de cada paso depende solo de (semilla, estación, paso): el ruido sale de un
generador sembrado con esa tupla. Así el paso 37 da siempre lo mismo, sin importar
cuántas estaciones se simulen ni en qué orden, y los tests pueden pedir cualquier paso.
"""

import math
import random
from dataclasses import dataclass
from enum import StrEnum

# Valores típicos por variable (caudal del Rímac en estiaje, nivel en metros, lluvia en mm).
BASELINES = {"discharge": 85.0, "water_level": 2.0, "rainfall": 0.5}
DEFAULT_BASELINE = 10.0
NOISE_SIGMA = 0.02  # ruido gaussiano relativo: ±2 % típico

DROP_FACTOR = 0.4  # tras la caída el caudal queda al 40 %: 85 → 34 m3/s, delta de 51
RISE_FACTOR = 2.0  # la subida duplica el valor: nivel 2 m → 4 m, supera el umbral de 3,5
RISE_STEPS = 30  # la subida tarda 30 pasos (5 min a 10 s por paso)

# Escenario de demo de SPEC: represamiento entre Santa Eulalia y Chaclacayo.
RIMAC_DOWNSTREAM = "RIM-CHA-01"  # registra la caída brusca de caudal
RIMAC_UPSTREAM = "RIM-SEU-01"  # deja de reportar 4 minutos después
RIMAC_SILENCE_DELAY_S = 240


class Behavior(StrEnum):
    NORMAL = "normal"
    RISE = "rise"
    DROP = "drop"
    SILENCE = "silence"


class Scenario(StrEnum):
    NORMAL = "normal"
    RISE = "rise"
    DROP = "drop"
    SILENCE = "silence"
    RIMAC = "rimac"


@dataclass(frozen=True)
class StationPlan:
    code: str
    variable: str
    behavior: Behavior
    event_step: int = 0  # paso en que empieza la subida, la caída o el silencio


class MissingStationsError(Exception):
    pass


def value_at(plan: StationPlan, seed: int, step: int) -> float | None:
    """Valor del paso `step`, o None si la estación está en silencio."""
    level = _level(plan, step)
    if level is None:
        return None
    base = BASELINES.get(plan.variable, DEFAULT_BASELINE)
    noise = random.Random(f"{seed}:{plan.code}:{step}").gauss(0.0, NOISE_SIGMA)
    return round(max(0.0, base * level * (1.0 + noise)), 3)


def _level(plan: StationPlan, step: int) -> float | None:
    elapsed = step - plan.event_step
    match plan.behavior:
        case Behavior.NORMAL:
            return 1.0
        case Behavior.SILENCE:
            return None if elapsed >= 0 else 1.0
        case Behavior.DROP:
            return DROP_FACTOR if elapsed >= 0 else 1.0
        case Behavior.RISE:
            progress = min(max(elapsed, 0), RISE_STEPS) / RISE_STEPS
            return 1.0 + (RISE_FACTOR - 1.0) * progress


def build_plan(
    scenario: Scenario,
    stations: list[tuple[str, str]],
    *,
    event_step: int,
    interval_s: float,
) -> list[StationPlan]:
    """`stations` son pares (código, variable). En los escenarios simples todas las
    estaciones siguen el mismo comportamiento; `rimac` reproduce la demo de SPEC."""
    if scenario is not Scenario.RIMAC:
        behavior = Behavior(scenario.value)
        return [StationPlan(code, variable, behavior, event_step) for code, variable in stations]

    codes = {code for code, _ in stations}
    missing = {RIMAC_DOWNSTREAM, RIMAC_UPSTREAM} - codes
    if missing:
        raise MissingStationsError(f"el escenario rimac necesita las estaciones {sorted(missing)}")
    silence_step = event_step + math.ceil(RIMAC_SILENCE_DELAY_S / interval_s)
    special = {
        RIMAC_DOWNSTREAM: (Behavior.DROP, event_step),
        RIMAC_UPSTREAM: (Behavior.SILENCE, silence_step),
    }
    return [
        StationPlan(code, variable, *special.get(code, (Behavior.NORMAL, 0)))
        for code, variable in stations
    ]
