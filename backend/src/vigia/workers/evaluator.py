"""Worker evaluator: evalúa umbral y tasa de cambio desde ingest.evaluation_queue.

Stub de Sprint 0: solo late. Se implementa en VIG-14.
"""

from vigia.workers._runner import run_worker


def main() -> None:
    run_worker("evaluator", interval_s=5.0)


if __name__ == "__main__":
    main()
