import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from willay.shared.clock import FakeClock
from willay.workers.healthcheck import is_alive

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _touch_at(path: Path, instant: datetime) -> Path:
    path.touch()
    os.utime(path, (instant.timestamp(), instant.timestamp()))
    return path


def test_fresh_heartbeat_is_alive(tmp_path: Path) -> None:
    heartbeat = _touch_at(tmp_path / "evaluator.alive", NOW - timedelta(seconds=10))
    assert is_alive(heartbeat, FakeClock(NOW))


def test_stale_heartbeat_is_dead(tmp_path: Path) -> None:
    heartbeat = _touch_at(tmp_path / "evaluator.alive", NOW - timedelta(seconds=31))
    assert not is_alive(heartbeat, FakeClock(NOW))


def test_missing_heartbeat_is_dead(tmp_path: Path) -> None:
    assert not is_alive(tmp_path / "never-started.alive", FakeClock(NOW))
