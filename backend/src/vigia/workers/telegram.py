"""Worker telegram: long polling de getUpdates para vinculación y confirmaciones.

Stub de Sprint 0: solo late. Se implementa en VIG-21.
"""

from vigia.workers._runner import run_worker


def main() -> None:
    run_worker("telegram", interval_s=5.0)


if __name__ == "__main__":
    main()
