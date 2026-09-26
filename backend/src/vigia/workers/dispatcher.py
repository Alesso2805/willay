"""Worker dispatcher: envía alertas por correo y Telegram con reintentos.

Stub de Sprint 0: solo late. Se implementa en VIG-20.
"""

from vigia.workers._runner import run_worker


def main() -> None:
    run_worker("dispatcher", interval_s=5.0)


if __name__ == "__main__":
    main()
