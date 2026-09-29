"""Worker dispatcher (VIG-20): `python -m vigia.workers.dispatcher`.

Envía las alertas de correo pendientes. Despierta con LISTEN vigia_alerts en cuanto el
evaluador o el worker silence confirman un incidente nuevo, y consulta cada 5 s por si un
aviso se perdió y para tomar los reintentos que ya vencieron. Telegram llega con VIG-22.
"""

import asyncio

from vigia.alerts.application.dispatch import EmailDispatcher, EmailSender
from vigia.alerts.infrastructure.smtp import SmtpEmailSender
from vigia.alerts.infrastructure.sql_dispatch import SqlDispatchQueue
from vigia.shared import notifications
from vigia.shared.clock import Clock, SystemClock
from vigia.shared.config import Settings
from vigia.shared.db import create_engine
from vigia.shared.pg_listen import asyncpg_dsn, listen
from vigia.workers._runner import run_async_worker, run_loop

NAME = "dispatcher"
POLL_INTERVAL_S = 5.0
BATCH_SIZE = 10


async def run_dispatcher(
    settings: Settings,
    stop: asyncio.Event,
    *,
    clock: Clock | None = None,
    sender: EmailSender | None = None,
    poll_interval_s: float = POLL_INTERVAL_S,
    batch_size: int = BATCH_SIZE,
) -> None:
    clock = clock or SystemClock()
    engine = create_engine(settings.database_url)
    email = EmailDispatcher(
        SqlDispatchQueue(engine),
        sender
        or SmtpEmailSender(
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_from,
            timeout_s=settings.smtp_timeout_s,
            start_tls=settings.smtp_start_tls,
            username=settings.smtp_username,
            password=settings.smtp_password,
        ),
        clock,
        settings.public_url,
    )

    async def tick() -> bool:
        result = await email.dispatch(batch_size)
        return result.claimed == batch_size  # lote lleno: probablemente quedan más

    try:
        dsn = asyncpg_dsn(settings.database_url)
        async with listen(dsn, notifications.ALERTS) as wakeup:
            heartbeat = settings.heartbeat_dir / f"{NAME}.alive"
            await run_loop(NAME, poll_interval_s, heartbeat, stop, tick, wakeup)
    finally:
        await engine.dispose()


def main() -> None:
    run_async_worker(NAME, run_dispatcher)


if __name__ == "__main__":
    main()
