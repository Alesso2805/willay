"""Worker healthcheck: `python -m vigia.workers.healthcheck <name>`.

Exits 0 if the worker's heartbeat file was touched less than `MAX_AGE` ago. Used by the
Docker Compose healthcheck, since workers expose no HTTP.
"""

import sys
from datetime import timedelta
from pathlib import Path

from vigia.shared.clock import Clock, SystemClock
from vigia.shared.config import get_settings

MAX_AGE = timedelta(seconds=30)


def is_alive(heartbeat: Path, clock: Clock, max_age: timedelta = MAX_AGE) -> bool:
    try:
        mtime = heartbeat.stat().st_mtime
    except FileNotFoundError:
        return False
    return clock.now().timestamp() - mtime < max_age.total_seconds()


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m vigia.workers.healthcheck <worker-name>")
    heartbeat = get_settings().heartbeat_dir / f"{sys.argv[1]}.alive"
    sys.exit(0 if is_alive(heartbeat, SystemClock()) else 1)


if __name__ == "__main__":
    main()
