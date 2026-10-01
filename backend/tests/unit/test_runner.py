import asyncio
from pathlib import Path

from willay.workers._runner import run_loop


async def test_loop_touches_heartbeat_and_stops_on_signal(tmp_path: Path) -> None:
    heartbeat = tmp_path / "hb" / "evaluator.alive"
    stop = asyncio.Event()
    ticks = 0

    async def tick() -> None:
        nonlocal ticks
        ticks += 1
        if ticks == 3:
            stop.set()

    await asyncio.wait_for(run_loop("evaluator", 0.01, heartbeat, stop, tick), timeout=1.0)

    assert heartbeat.exists()
    assert ticks == 3


async def test_loop_exits_promptly_when_stopped_during_wait(tmp_path: Path) -> None:
    heartbeat = tmp_path / "worker.alive"
    stop = asyncio.Event()
    # Long interval: if stopping did not interrupt the wait, the test would hang.
    task = asyncio.create_task(run_loop("silence", 60.0, heartbeat, stop))
    # The heartbeat is written from a thread: wait for it (up to 2 s) instead of a fixed
    # pause, which was flaky on slow CI runners.
    for _ in range(200):
        if heartbeat.exists():
            break
        await asyncio.sleep(0.01)
    assert heartbeat.exists()
    stop.set()
    await asyncio.wait_for(task, timeout=1.0)


async def test_a_notification_wakes_the_loop_before_the_interval(tmp_path: Path) -> None:
    stop, wakeup = asyncio.Event(), asyncio.Event()
    ticks = 0

    async def tick() -> None:
        nonlocal ticks
        ticks += 1
        if ticks == 2:
            stop.set()

    task = asyncio.create_task(
        run_loop("evaluator", 60.0, tmp_path / "hb.alive", stop, tick, wakeup)
    )
    await asyncio.sleep(0.05)
    assert ticks == 1  # waiting out the 60 s interval...
    wakeup.set()  # ...until a NOTIFY arrives
    await asyncio.wait_for(task, timeout=1.0)
    assert ticks == 2


async def test_a_notification_during_work_is_not_lost(tmp_path: Path) -> None:
    stop, wakeup = asyncio.Event(), asyncio.Event()
    ticks = 0

    async def tick() -> None:
        nonlocal ticks
        ticks += 1
        if ticks == 1:
            wakeup.set()  # the wakeup arrives while the previous batch is running
        else:
            stop.set()

    await asyncio.wait_for(
        run_loop("evaluator", 60.0, tmp_path / "hb.alive", stop, tick, wakeup), timeout=1.0
    )
    assert ticks == 2


async def test_pending_work_repeats_without_waiting(tmp_path: Path) -> None:
    stop = asyncio.Event()
    batches = [True, True, False]

    async def tick() -> bool:
        more = batches.pop(0)
        if not batches:
            stop.set()
        return more

    await asyncio.wait_for(run_loop("evaluator", 60.0, tmp_path / "hb.alive", stop, tick), 1.0)
    assert batches == []


async def test_a_failing_tick_keeps_the_worker_alive_but_stops_the_heartbeat(
    tmp_path: Path,
) -> None:
    heartbeat = tmp_path / "hb.alive"
    stop = asyncio.Event()
    calls = 0

    async def tick() -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            stop.set()
        raise ConnectionError("database not responding")

    await asyncio.wait_for(run_loop("evaluator", 0.01, heartbeat, stop, tick), timeout=1.0)

    assert calls == 3  # it kept trying
    assert not heartbeat.exists()  # but the healthcheck will report it as down
