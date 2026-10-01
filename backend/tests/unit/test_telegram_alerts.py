import traceback
from datetime import UTC, datetime

import pytest

from tests.unit.test_email_alerts import MESSAGE
from vigia.alerts.application.dispatch import DeliveryError, TelegramChannel
from vigia.alerts.application.telegram_bot import TelegramError
from vigia.alerts.domain.confirmation import ConfirmOutcome
from vigia.alerts.domain.telegram import (
    CLICK_ANSWER,
    ESCALATION_NOTE,
    MAX_CLICK_ANSWER,
    closed_text,
    closing_note,
    compose_alert_text,
)


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


def test_every_click_gets_an_answer_that_fits_in_telegram() -> None:
    assert set(CLICK_ANSWER) == set(ConfirmOutcome)
    assert all(0 < len(text) <= MAX_CLICK_ANSWER for text in CLICK_ANSWER.values())


ACK_AT = datetime(2026, 11, 20, 14, 5, tzinfo=UTC)


@pytest.mark.parametrize(
    ("outcome", "by", "note"),
    [
        (ConfirmOutcome.CONFIRMED, "Ana", "Confirmado por Ana el 20/11/2026 09:05 (America/Lima)."),
        (
            ConfirmOutcome.ALREADY_ACKNOWLEDGED,
            "María",
            "Confirmado por María el 20/11/2026 09:05 (America/Lima).",
        ),
        (
            ConfirmOutcome.USED,
            None,
            "Confirmado por otra persona el 20/11/2026 09:05 (America/Lima).",
        ),
        (
            ConfirmOutcome.ALREADY_RESOLVED,
            None,
            "Incidente resuelto: ya no hace falta confirmarlo.",
        ),
        (ConfirmOutcome.EXPIRED, None, "El botón venció (vale 24 horas)."),
        (ConfirmOutcome.UNKNOWN, None, None),
        (ConfirmOutcome.NOT_YOURS, None, None),  # un clic ajeno no dice nada del incidente
    ],
)
def test_the_button_is_replaced_by_who_confirmed_and_when(
    outcome: ConfirmOutcome, by: str | None, note: str | None
) -> None:
    assert closing_note(outcome, by, ACK_AT, "America/Lima") == note


def test_a_handled_alert_drops_the_escalation_warning() -> None:
    sent = compose_alert_text(MESSAGE)
    closed = closed_text(sent, "Confirmado por Ana.")

    assert ESCALATION_NOTE in sent
    assert ESCALATION_NOTE not in closed  # ya no escala: el aviso dejaría de ser cierto
    assert closed.startswith("Vigía · CRÍTICO: Cambio brusco en Chosica")
    assert "no reemplaza los avisos oficiales" in closed  # el descargo se queda
    assert closed.endswith("\n\nConfirmado por Ana.")
