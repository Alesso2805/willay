"""Bucle común de los workers: latido, despertar, log y parada ordenada con SIGTERM/SIGINT.

Cada vuelta ejecuta `tick`. Luego el worker espera el intervalo (consulta de respaldo)
salvo que:
- `tick` devuelva True: quedó trabajo pendiente y se repite sin esperar;
- llegue un aviso por `wakeup` (LISTEN/NOTIFY): despierta en el acto.

El latido solo se toca si la vuelta terminó bien: si la base se cae, el proceso sigue
vivo (reintenta en la próxima vuelta) pero su healthcheck se pone en rojo.
"""

import asyncio
import signal
from collections.abc import Awaitable, Callable
from pathlib import Path

import structlog

from vigia.shared.config import Settings, get_settings
from vigia.shared.logging import configure_logging

Tick = Callable[[], Awaitable[bool | None]]
WorkerBody = Callable[[Settings, asyncio.Event], Awaitable[None]]


async def _noop() -> None:
    return None


async def run_loop(
    name: str,
    interval_s: float,
    heartbeat: Path,
    stop: asyncio.Event,
    tick: Tick = _noop,
    wakeup: asyncio.Event | None = None,
) -> None:
    log = structlog.get_logger().bind(worker=name)
    # I/O de disco en un hilo para no bloquear el event loop (ASYNC240).
    await asyncio.to_thread(heartbeat.parent.mkdir, parents=True, exist_ok=True)
    log.info("worker_started", interval_s=interval_s)
    while not stop.is_set():
        # Se limpia ANTES del trabajo: un aviso que llegue mientras se procesa deja el
        # evento puesto y la espera siguiente termina al instante (no se pierde).
        if wakeup is not None:
            wakeup.clear()
        try:
            more = await tick()
        except Exception:
            log.exception("worker_tick_failed")
            more = False
        else:
            # El latido va después de una vuelta correcta: si el trabajo se cuelga o
            # falla una y otra vez, el healthcheck lo detecta.
            await asyncio.to_thread(heartbeat.touch)
        if not more:
            await _wait(stop, wakeup, interval_s)
    log.info("worker_stopped")


async def _wait(stop: asyncio.Event, wakeup: asyncio.Event | None, timeout_s: float) -> None:
    """Espera hasta `timeout_s`, la parada o un aviso, lo que ocurra primero."""
    waiters = [asyncio.create_task(stop.wait())]
    if wakeup is not None:
        waiters.append(asyncio.create_task(wakeup.wait()))
    try:
        await asyncio.wait(waiters, timeout=timeout_s, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            waiter.cancel()


def run_async_worker(name: str, body: WorkerBody) -> None:
    """Punto de entrada de un worker: logging, señales de parada y su cuerpo async."""
    settings = get_settings()
    configure_logging(settings.log_level)

    async def main() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        await body(settings, stop)

    asyncio.run(main())


def run_worker(name: str, interval_s: float, tick: Tick = _noop) -> None:
    """Workers sencillos (aún sin despertar por aviso): un tick cada `interval_s`."""

    async def body(settings: Settings, stop: asyncio.Event) -> None:
        await run_loop(name, interval_s, settings.heartbeat_dir / f"{name}.alive", stop, tick)

    run_async_worker(name, body)
