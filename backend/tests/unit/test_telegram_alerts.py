import traceback

import pytest

from tests.unit.test_email_alerts import MESSAGE
from vigia.alerts.application.dispatch import DeliveryError, TelegramChannel
from vigia.alerts.application.telegram_bot import TelegramError
from vigia.alerts.domain.telegram import compose_alert_text


def test_the_telegram_alert_has_the_same_summary_as_the_email() -> None:
    text = compose_alert_text(MESSAGE)
    lines = text.splitlines()
    assert lines[0] == "Vigía · CRÍTICO: Cambio brusco en Chosica"
    assert "Estación: RIM-CHA-01 · Chaclacayo (aguas abajo)" in lines
    assert "Valor: 35.11 m3/s" in lines
    assert "Abierto: 20/11/2026 09:00 (America/Lima)" in lines
    assert "no reemplaza los avisos oficiales" in text


class Rejecting:
    async def send_alert(self, chat_id: int, text: str, callback_data: str) -> None:
        raise TelegramError("sendMessage: 403 Forbidden: bot was blocked by the user")


async def test_a_rejected_message_is_a_delivery_failure_to_retry() -> None:
    with pytest.raises(DeliveryError) as caught:
        await TelegramChannel(Rejecting()).deliver("4242", MESSAGE, "t" * 43)
    assert "403" in str(caught.value)
    # Sin la excepción original encadenada: nada de Telegram viaja en la traza.
    assert "TelegramError" not in "".join(traceback.format_exception(caught.value))
