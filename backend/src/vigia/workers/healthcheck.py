"""Healthcheck de un worker: `python -m vigia.workers.healthcheck <nombre>`.

Sale con 0 si el archivo de latido del worker se tocó hace menos de `MAX_AGE`.
Lo usa el healthcheck de Docker Compose; los workers no exponen HTTP.
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
        sys.exit("uso: python -m vigia.workers.healthcheck <nombre-del-worker>")
    heartbeat = get_settings().heartbeat_dir / f"{sys.argv[1]}.alive"
    sys.exit(0 if is_alive(heartbeat, SystemClock()) else 1)


if __name__ == "__main__":
    main()
