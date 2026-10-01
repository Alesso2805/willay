"""Dispatcher worker (VIG-20, VIG-22): `python -m vigia.workers.dispatcher`.

Sends pending alerts by email and Telegram. Wakes on LISTEN vigia_alerts when new alerts are
committed, and polls every 5 s for lost notifications and due retries. Each channel runs on
its own, so a Telegram outage does not stop email (SPEC); without a bot token, Telegram alerts
stay pending until one is configured.
"""

import asyncio

import structlog

from vigia.alerts.application.dispatch import (
    AlertDispatcher,
    DispatchResult,
    EmailDispatcher,
    EmailSender,
    TelegramDispatcher,
    TelegramSender,
)
from vigia.alerts.infrastructure.smtp import SmtpEmailSender
from vigia.alerts.infrastructure.sql_dispatch import SqlDispatchQueue
from vigia.alerts.infrastructure.telegram_api import TelegramBotApi
from vigia.shared import notifications
from vigia.shared.clock import Clock, SystemClock
from vigia.shared.config import Settings
from vigia.shared.db import create_engine
from vigia.shared.pg_listen import asyncpg_dsn, listen
from vigia.workers._runner import run_async_worker, run_loop

NAME = "dispatcher"
POLL_INTERVAL_S = 5.0
BATCH_SIZE = 10

log = structlog.get_logger()


async def run_dispatcher(
    settings: Settings,
    stop: asyncio.Event,
    *,
    clock: Clock | None = None,
    sender: EmailSender | None = None,
    telegram: TelegramSender | None = None,
    poll_interval_s: float = POLL_INTERVAL_S,
    batch_size: int = BATCH_SIZE,
) -> None:
    clock = clock or SystemClock()
    engine = create_engine(settings.database_url)
    queue = SqlDispatchQueue(engine)
    smtp = sender or SmtpEmailSender(
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_from,
        timeout_s=settings.smtp_timeout_s,
        start_tls=settings.smtp_start_tls,
        username=settings.smtp_username,
        password=settings.smtp_password,
    )
    dispatchers: list[AlertDispatcher] = [EmailDispatcher(queue, smtp, clock, settings.public_url)]
    bot: TelegramBotApi | None = None
    if telegram is None and settings.telegram_bot_token is not None:
        bot = TelegramBotApi(
            settings.telegram_bot_token.get_secret_value(), base_url=settings.telegram_api_url
        )
    telegram_sender: TelegramSender | None = telegram if telegram is not None else bot
    if telegram_sender is not None:
        dispatchers.append(TelegramDispatcher(queue, telegram_sender, clock))

    async def tick() -> bool:
        results = await asyncio.gather(
            *(d.dispatch(batch_size) for d in dispatchers), return_exceptions=True
        )
        done = [r for r in results if isinstance(r, DispatchResult)]
        for result in results:
            if isinstance(result, BaseException):
                log.error("dispatch_channel_failed", exc_info=result)
        if not done:
            raise RuntimeError("no channel could dispatch")  # shows up in the healthcheck
        return any(r.claimed == batch_size for r in done)  # full batch: more remain

    try:
        dsn = asyncpg_dsn(settings.database_url)
        async with listen(dsn, notifications.ALERTS) as wakeup:
            heartbeat = settings.heartbeat_dir / f"{NAME}.alive"
            await run_loop(NAME, poll_interval_s, heartbeat, stop, tick, wakeup)
    finally:
        if bot is not None:
            await bot.aclose()
        await engine.dispose()


def main() -> None:
    run_async_worker(NAME, run_dispatcher)


if __name__ == "__main__":
    main()
