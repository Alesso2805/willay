"""Telegram worker (VIG-21, VIG-22): `python -m willay.workers.telegram`.

Long polling with `getUpdates` to link contacts and receive alert confirmation button clicks.
Without `WILLAY_TELEGRAM_BOT_TOKEN` it starts disabled and only beats, so `docker compose up`
works without a bot.
"""

import asyncio

import structlog

from willay.alerts.application.telegram_bot import TelegramApi, TelegramPoller
from willay.alerts.infrastructure.sql_confirmation import SqlConfirmationRepository
from willay.alerts.infrastructure.sql_contact_links import SqlContactLinkRepository
from willay.alerts.infrastructure.telegram_api import TelegramBotApi
from willay.incidents.infrastructure.incidents_repository import SqlIncidentRepository
from willay.shared.audit import SqlAuditLog
from willay.shared.clock import Clock, SystemClock
from willay.shared.config import Settings
from willay.shared.db import create_engine
from willay.workers._runner import run_async_worker, run_loop

NAME = "telegram"
POLL_TIMEOUT_S = 20  # under the 30 s healthcheck: the heartbeat lands between polls
RETRY_S = 5.0  # if Telegram does not answer, do not retry in a tight loop

log = structlog.get_logger()


async def run_telegram(
    settings: Settings,
    stop: asyncio.Event,
    *,
    clock: Clock | None = None,
    api: TelegramApi | None = None,
    poll_timeout_s: int = POLL_TIMEOUT_S,
) -> None:
    heartbeat = settings.heartbeat_dir / f"{NAME}.alive"
    owned: TelegramBotApi | None = None
    bot: TelegramApi
    if api is not None:
        bot = api
    else:
        if settings.telegram_bot_token is None:
            log.warning("telegram_disabled", reason="WILLAY_TELEGRAM_BOT_TOKEN is not set")
            await run_loop(NAME, 30.0, heartbeat, stop)  # heartbeat only
            return
        owned = TelegramBotApi(
            settings.telegram_bot_token.get_secret_value(), base_url=settings.telegram_api_url
        )
        bot = owned

    clock = clock or SystemClock()
    engine = create_engine(settings.database_url)
    poller = TelegramPoller(
        bot,
        engine.begin,
        clock,
        SqlContactLinkRepository,
        SqlAuditLog,
        SqlConfirmationRepository,
        SqlIncidentRepository,
    )

    async def tick() -> bool:
        # Long polling takes up to `poll_timeout_s`: do not wait for it on shutdown.
        polling = asyncio.create_task(poller.poll(poll_timeout_s))
        stopping = asyncio.create_task(stop.wait())
        done, pending = await asyncio.wait({polling, stopping}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if polling in done:
            polling.result()  # on failure, run_loop logs it and retries after RETRY_S
            return True  # keep polling without waiting
        return False

    try:
        await run_loop(NAME, RETRY_S, heartbeat, stop, tick)
    finally:
        if owned is not None:
            await owned.aclose()
        await engine.dispose()


def main() -> None:
    run_async_worker(NAME, run_telegram)


if __name__ == "__main__":
    main()
