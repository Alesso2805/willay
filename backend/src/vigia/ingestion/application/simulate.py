"""Caso de uso: correr una simulación enviando un lote por estación en cada paso.

Corre en tiempo real a propósito: el detector de silencio y el escalamiento miden con
el reloj de verdad, así que acelerar el tiempo del simulador no acelera la demo.
El reloj, la espera y el envío se inyectan para probarlo sin esperas ni red.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from vigia.ingestion.domain.simulation import StationPlan, value_at
from vigia.shared.clock import Clock

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class SimulatedStation:
    plan: StationPlan
    api_key: str


class ReadingSender(Protocol):
    async def send(self, api_key: str, measured_at: datetime, value: float) -> int:
        """Envía un lote de una lectura. Devuelve el código HTTP (0 si no hubo respuesta)."""
        ...


@dataclass(frozen=True)
class TickReport:
    step: int
    at: datetime
    values: dict[str, float | None]  # None = la estación calla en este paso
    statuses: dict[str, int]  # código HTTP por estación que envió


async def run_simulation(
    stations: list[SimulatedStation],
    *,
    seed: int,
    interval_s: float,
    steps: int | None,
    clock: Clock,
    sleep: Sleep,
    sender: ReadingSender,
    on_tick: Callable[[TickReport], None],
) -> None:
    start = clock.now()
    step = 0
    while steps is None or step < steps:
        # Se agenda contra el inicio, no contra el paso anterior: el tiempo que tarda el
        # envío no se acumula y la estación mantiene su intervalo esperado.
        wait = (start + timedelta(seconds=interval_s * step) - clock.now()).total_seconds()
        if wait > 0:
            await sleep(wait)
        now = clock.now()

        values = {s.plan.code: value_at(s.plan, seed, step) for s in stations}
        batches = [(s, v) for s in stations if (v := values[s.plan.code]) is not None]
        codes = await asyncio.gather(*(sender.send(s.api_key, now, v) for s, v in batches))
        statuses = {s.plan.code: code for (s, _), code in zip(batches, codes, strict=True)}
        on_tick(TickReport(step, now, values, statuses))
        step += 1
