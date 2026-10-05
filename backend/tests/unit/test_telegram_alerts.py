import traceback
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from tests.unit.test_email_alerts import MESSAGE
from willay.alerts.application.dispatch import DeliveryError, TelegramChannel
from willay.alerts.application.telegram_bot import TelegramError
from willay.alerts.domain.confirmation import ConfirmOutcome
from willay.alerts.domain.telegram import (
    MAX_CLICK_ANSWER,
    click_answer,
    closed_text,
    closing_note,
    compose_alert_text,
    escalation_note,
)
from willay.shared.i18n import CATALOGS
from willay.shared.languages import Language

ESCALATION_NOTE = escalation_note(Language.ES)


def test_the_telegram_alert_has_the_same_summary_as_the_email() -> None:
    text = compose_alert_text(MESSAGE)
    lines = text.splitlines()
    assert lines[0] == "Willay · CRÍTICO: Cambio brusco en Chosica"
    assert "Estación: RIM-CHA-01 · Chaclacayo (aguas abajo)" in lines
    assert "Valor: 35.11 m3/s" in lines
    assert "Abierto: 20/11/2026 09:00 (America/Lima)" in lines
    assert "no reemplaza los avisos oficiales" in text


def test_an_english_contact_gets_the_telegram_alert_in_english() -> None:
    text = compose_alert_text(replace(MESSAGE, language=Language.EN))
    lines = text.splitlines()
    assert lines[0] == "Willay · CRITICAL: Sudden change in Chosica"
    assert "Opened: Nov 20, 2026, 09:00 (America/Lima)" in lines
    assert escalation_note(Language.EN) in lines
    assert "it does not replace official warnings" in text


class Rejecting:
    async def send_alert(self, chat_id: int, text: str, callback_data: str, button: str) -> None:
        raise TelegramError("sendMessage: 403 Forbidden: bot was blocked by the user")


async def test_a_rejected_message_is_a_delivery_failure_to_retry() -> None:
    with pytest.raises(DeliveryError) as caught:
        await TelegramChannel(Rejecting()).deliver("4242", MESSAGE, "t" * 43)
    assert "403" in str(caught.value)
    # The original exception is not chained, so nothing from Telegram leaks into the traceback.
    assert "TelegramError" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("language", list(Language))
@pytest.mark.parametrize("outcome", list(ConfirmOutcome))
def test_every_click_gets_an_answer_that_fits_in_telegram(
    outcome: ConfirmOutcome, language: Language
) -> None:
    assert CATALOGS[language].get(f"alerts.telegram.click.{outcome}")
    assert 0 < len(click_answer(outcome, language)) <= MAX_CLICK_ANSWER


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
        (ConfirmOutcome.NOT_YOURS, None, None),  # a stranger's click reveals nothing
    ],
)
def test_the_button_is_replaced_by_who_confirmed_and_when(
    outcome: ConfirmOutcome, by: str | None, note: str | None
) -> None:
    assert closing_note(outcome, by, ACK_AT, "America/Lima", Language.ES) == note


def test_the_note_is_in_the_language_of_the_contact() -> None:
    assert closing_note(ConfirmOutcome.CONFIRMED, None, ACK_AT, "America/Lima", Language.EN) == (
        "Acknowledged by someone else on Nov 20, 2026, 09:05 (America/Lima)."
    )


def test_a_handled_alert_drops_the_escalation_warning() -> None:
    sent = compose_alert_text(MESSAGE)
    closed = closed_text(sent, "Confirmado por Ana.")

    assert ESCALATION_NOTE in sent
    assert ESCALATION_NOTE not in closed  # no longer escalating, so the warning would be false
    assert closed.startswith("Willay · CRÍTICO: Cambio brusco en Chosica")
    assert "no reemplaza los avisos oficiales" in closed  # the disclaimer stays
    assert closed.endswith("\n\nConfirmado por Ana.")


def test_the_warning_is_dropped_even_if_the_contact_changed_language_since() -> None:
    sent = compose_alert_text(MESSAGE)  # in Spanish
    closed = closed_text(sent, "Acknowledged by Ana.")  # the contact now reads English
    assert ESCALATION_NOTE not in closed
