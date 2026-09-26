"""Worker escalation: escala incidentes cuyo nivel venció sin confirmación.

Stub de Sprint 0: solo late. Se implementa en VIG-24.
"""

from vigia.workers._runner import run_worker


def main() -> None:
    run_worker("escalation", interval_s=15.0)


if __name__ == "__main__":
    main()
