"""Bucle común de los workers: latido, log y parada ordenada con SIGTERM/SIGINT.

En Sprint 0 los workers solo laten. Cada historia (VIG-14, 17, 20, 21, 24) reemplaza
`tick` por el trabajo real y añade el despertar por LISTEN/NOTIFY donde aplique.
"""

import asyncio
import contextlib
import signal
from collections.abc import Awaitable, Callable
from pathlib import Path

import structlog

from vigia.shared.config import get_settings
from vigia.shared.logging import configure_logging

Tick = Callable[[], Awaitable[None]]


async def _noop() -> None:
    return None


async def run_loop(
    name: str,
    interval_s: float,
    heartbeat: Path,
    stop: asyncio.Event,
    tick: Tick = _noop,
) -> None:
    log = structlog.get_logger().bind(worker=name)
    # I/O de disco en un hilo para no bloquear el event loop (ASYNC240).
    await asyncio.to_thread(heartbeat.parent.mkdir, parents=True, exist_ok=True)
    log.info("worker_started", interval_s=interval_s)
    while not stop.is_set():
        await tick()
        # El latido va después del tick: si el trabajo se cuelga, el healthcheck lo detecta.
        await asyncio.to_thread(heartbeat.touch)
        # Espera el intervalo, pero despierta en cuanto llega la señal de parada.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
    log.info("worker_stopped")


def run_worker(name: str, interval_s: float, tick: Tick = _noop) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    async def main() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        await run_loop(name, interval_s, settings.heartbeat_dir / f"{name}.alive", stop, tick)

    asyncio.run(main())
