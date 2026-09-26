import asyncio
from pathlib import Path

from vigia.workers._runner import run_loop


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
    # Intervalo largo: si la parada no interrumpiera la espera, el test se colgaría.
    task = asyncio.create_task(run_loop("silence", 60.0, heartbeat, stop))
    await asyncio.sleep(0.05)
    assert heartbeat.exists()
    stop.set()
    await asyncio.wait_for(task, timeout=1.0)
