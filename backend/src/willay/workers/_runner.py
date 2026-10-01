"""Common worker loop: heartbeat, wakeup, logging and graceful SIGTERM/SIGINT shutdown.

Each round runs `tick`, then waits for the fallback polling interval unless `tick` returns
True (work remains) or a `wakeup` (LISTEN/NOTIFY) arrives. The heartbeat is touched only after
a successful round: if the database is down the process stays alive but its healthcheck turns red.
"""

import asyncio
import signal
from collections.abc import Awaitable, Callable
from pathlib import Path

import structlog

from willay.shared.config import Settings, get_settings
from willay.shared.logging import configure_logging

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
    # Disk I/O in a thread so it does not block the event loop (ASYNC240).
    await asyncio.to_thread(heartbeat.parent.mkdir, parents=True, exist_ok=True)
    log.info("worker_started", interval_s=interval_s)
    while not stop.is_set():
        # Cleared BEFORE the work: a notification arriving mid-round leaves the event set,
        # so the next wait returns at once and the notification is not lost.
        if wakeup is not None:
            wakeup.clear()
        try:
            more = await tick()
        except Exception:
            log.exception("worker_tick_failed")
            more = False
        else:
            # Heartbeat only after a successful round, so the healthcheck catches work that
            # hangs or keeps failing.
            await asyncio.to_thread(heartbeat.touch)
        if not more:
            await _wait(stop, wakeup, interval_s)
    log.info("worker_stopped")


async def _wait(stop: asyncio.Event, wakeup: asyncio.Event | None, timeout_s: float) -> None:
    """Waits for `timeout_s`, shutdown or a wakeup, whichever comes first."""
    waiters = [asyncio.create_task(stop.wait())]
    if wakeup is not None:
        waiters.append(asyncio.create_task(wakeup.wait()))
    try:
        await asyncio.wait(waiters, timeout=timeout_s, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            waiter.cancel()


def run_async_worker(name: str, body: WorkerBody) -> None:
    """Worker entry point: logging, shutdown signals and its async body."""
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
    """Simple workers (no wakeup notifications yet): one tick every `interval_s`."""

    async def body(settings: Settings, stop: asyncio.Event) -> None:
        await run_loop(name, interval_s, settings.heartbeat_dir / f"{name}.alive", stop, tick)

    run_async_worker(name, body)
