import hashlib
import json
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from willay.alerts.application.dispatch import (
    ClaimedAlert,
    DeliveryError,
    DispatchResult,
    EmailDispatcher,
)
from willay.alerts.domain.alerts import Channel
from willay.alerts.domain.delivery import AckToken, hash_ack_token, new_ack_token, retry_at
from willay.alerts.domain.email import AlertMessage, EmailContent, compose_email
from willay.shared.clock import FakeClock
from willay.shared.logging import configure_logging

T0 = datetime(2026, 11, 20, 14, 0, tzinfo=UTC)  # 09:00 in Lima (UTC-5)

MESSAGE = AlertMessage(
    contact_name="Óscar Operador",
    organization_name="Demo Rímac",
    timezone="America/Lima",
    zone_name="Chosica",
    severity="critical",
    rule_type="rate_of_change",
    station_code="RIM-CHA-01",
    station_name="Chaclacayo (aguas abajo)",
    unit="m3/s",
    trigger_value=35.11,
    opened_at=T0,
    level_order=1,
)


@pytest.mark.parametrize(
    ("failed_attempt", "wait"),
    [(1, timedelta(seconds=5)), (2, timedelta(seconds=10)), (3, timedelta(seconds=20)), (4, None)],
)
def test_three_exponential_retries_then_give_up(
    failed_attempt: int, wait: timedelta | None
) -> None:
    retry = retry_at(failed_attempt, T0)
    assert retry == (T0 + wait if wait is not None else None)


def test_the_ack_token_has_256_bits_and_only_its_hash_is_kept() -> None:
    first, second = new_ack_token(T0), new_ack_token(T0)
    assert len(first.token) == 43  # base64url of 32 bytes: fits Telegram's 64-char limit
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", first.token)
    assert first.token_hash == hashlib.sha256(first.token.encode()).hexdigest()
    assert first.token_hash == hash_ack_token(first.token)
    assert first.token != second.token
    assert first.expires_at == T0 + timedelta(hours=24)


def test_the_email_has_zone_severity_value_local_time_and_link() -> None:
    content = compose_email(MESSAGE, "http://localhost:8000/confirmar/abc")
    assert content.subject == "[Willay] CRÍTICO · Cambio brusco en Chosica (RIM-CHA-01)"
    body = content.body
    assert body.startswith("Hola Óscar Operador:")
    assert "incidente CRÍTICO en la zona Chosica" in body
    assert "RIM-CHA-01 · Chaclacayo (aguas abajo)" in body
    assert "Valor:     35.11 m3/s" in body
    assert "Abierto:   20/11/2026 09:00 (America/Lima)" in body  # local time, not UTC
    assert "http://localhost:8000/confirmar/abc" in body
    assert "no reemplaza los avisos oficiales" in body


@pytest.mark.parametrize(
    ("severity", "phrase"),
    [
        ("critical", "abrió un incidente CRÍTICO en"),
        ("warning", "abrió un incidente de ADVERTENCIA en"),
        ("info", "abrió un incidente INFORMATIVO en"),
    ],
)
def test_the_opening_sentence_agrees_with_the_severity(severity: str, phrase: str) -> None:
    assert phrase in compose_email(replace(MESSAGE, severity=severity), "http://x").body


def test_a_silence_email_shows_the_last_value_or_says_there_is_none() -> None:
    silence = replace(MESSAGE, rule_type="silence", trigger_value=None)
    content = compose_email(silence, "http://x/confirmar/abc")
    assert "Estación sin reportar" in content.subject
    assert "Último:    sin dato" in content.body


def _claimed(attempt: int = 1) -> ClaimedAlert:
    return ClaimedAlert(uuid4(), uuid4(), uuid4(), uuid4(), 1, attempt, "ana@x.test", MESSAGE)


class Queue:
    def __init__(self, *alerts: ClaimedAlert, lost: bool = False) -> None:
        self.alerts, self.lost = list(alerts), lost
        self.tokens: list[AckToken] = []
        self.delivered: list[ClaimedAlert] = []
        self.failures: list[tuple[str, datetime | None]] = []

    async def claim(
        self, channel: Channel, now: datetime, visible_again_at: datetime, limit: int
    ) -> list[ClaimedAlert]:
        assert (channel, visible_again_at - now) == (Channel.EMAIL, timedelta(seconds=60))
        return self.alerts[:limit]

    async def attach_token(self, alert: ClaimedAlert, token: AckToken) -> bool:
        self.tokens.append(token)
        return not self.lost

    async def sent(self, alert: ClaimedAlert, now: datetime) -> None:
        self.delivered.append(alert)

    async def failed(
        self, alert: ClaimedAlert, error: str, retry: datetime | None, now: datetime
    ) -> None:
        self.failures.append((error, retry))


class Sender:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.messages: list[tuple[str, EmailContent]] = []

    async def send(self, to: str, content: EmailContent) -> None:
        if self.error is not None:
            raise self.error
        self.messages.append((to, content))


def _dispatcher(queue: Queue, sender: Sender) -> EmailDispatcher:
    return EmailDispatcher(queue, sender, FakeClock(T0), "http://localhost:8000/")


async def test_a_sent_alert_carries_the_link_of_its_stored_token() -> None:
    queue, sender = Queue(_claimed()), Sender()
    assert await _dispatcher(queue, sender).dispatch(10) == DispatchResult(1, 1, 0)

    [(to, content)] = sender.messages
    [token] = queue.tokens
    assert to == "ana@x.test"
    # The link carries the plain token; the database keeps only its hash.
    assert f"http://localhost:8000/confirmar/{token.token}" in content.body
    assert len(queue.delivered) == 1


async def test_a_failed_send_is_retried_with_backoff_and_the_last_one_is_final() -> None:
    queue, sender = Queue(_claimed(attempt=1), _claimed(attempt=4)), Sender(DeliveryError("boom"))
    assert await _dispatcher(queue, sender).dispatch(10) == DispatchResult(2, 0, 2)
    assert queue.failures == [("boom", T0 + timedelta(seconds=5)), ("boom", None)]


async def test_a_lost_claim_sends_nothing() -> None:
    queue, sender = Queue(_claimed(), lost=True), Sender()
    assert await _dispatcher(queue, sender).dispatch(10) == DispatchResult(1, 0, 0)
    assert sender.messages == []


async def test_an_unexpected_error_does_not_stop_the_other_alerts() -> None:
    class Flaky(Sender):
        """The first send blows up with a non-delivery error (a bug)."""

        calls = 0

        async def send(self, to: str, content: EmailContent) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("bug")
            await super().send(to, content)

    queue, sender = Queue(_claimed(), _claimed()), Flaky()
    result = await _dispatcher(queue, sender).dispatch(10)
    # The alert that hit an unexpected error stays claimed and is retried when the claim expires.
    assert result == DispatchResult(2, 1, 0)


async def test_the_send_is_logged_with_its_incident_correlation_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging()  # JSON lines, as the workers write them
    correlation_id = uuid4()
    queue, sender = Queue(replace(_claimed(), correlation_id=correlation_id)), Sender()
    await _dispatcher(queue, sender).dispatch(10)
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
    [sent] = [entry for entry in lines if entry["event"] == "alert_sent"]
    assert sent["correlation_id"] == str(correlation_id)
