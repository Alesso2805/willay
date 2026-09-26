"""Worker silence: detecta estaciones silenciosas y purga rate_limit_windows.

Stub de Sprint 0: solo late. Se implementa en VIG-17.
"""

from vigia.workers._runner import run_worker


def main() -> None:
    run_worker("silence", interval_s=15.0)


if __name__ == "__main__":
    main()
