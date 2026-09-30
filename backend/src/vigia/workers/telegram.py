"""Worker telegram (VIG-21, VIG-22): `python -m vigia.workers.telegram`.

Long polling con `getUpdates` para vincular contactos y recibir los clics en el botón de
confirmación de las alertas. Sin `VIGIA_TELEGRAM_BOT_TOKEN` arranca deshabilitado: solo
late, para que `docker compose up` funcione sin un bot creado.
"""

import asyncio

import structlog

from vigia.alerts.application.telegram_bot import TelegramApi, TelegramPoller
from vigia.alerts.infrastructure.sql_confirmation import SqlConfirmationRepository
from vigia.alerts.infrastructure.sql_contact_links import SqlContactLinkRepository
from vigia.alerts.infrastructure.telegram_api import TelegramBotApi
from vigia.incidents.infrastructure.incidents_repository import SqlIncidentRepository
from vigia.shared.audit import SqlAuditLog
from vigia.shared.clock import Clock, SystemClock
from vigia.shared.config import Settings
from vigia.shared.db import create_engine
from vigia.workers._runner import run_async_worker, run_loop

NAME = "telegram"
POLL_TIMEOUT_S = 20  # menos que los 30 s del healthcheck: el latido llega entre sondeos
RETRY_S = 5.0  # si Telegram no responde, no insistir en bucle

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
            log.warning("telegram_disabled", reason="falta VIGIA_TELEGRAM_BOT_TOKEN")
            await run_loop(NAME, 30.0, heartbeat, stop)  # solo late
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
        # El long polling tarda hasta `poll_timeout_s`: ante una parada no se lo espera.
        polling = asyncio.create_task(poller.poll(poll_timeout_s))
        stopping = asyncio.create_task(stop.wait())
        done, pending = await asyncio.wait({polling, stopping}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if polling in done:
            polling.result()  # si falló, run_loop lo registra y reintenta tras RETRY_S
            return True  # seguir sondeando sin esperar
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
