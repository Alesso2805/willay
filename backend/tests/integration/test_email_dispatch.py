"""VIG-20 (part 2): the dispatcher sends email alerts, which reach a real Mailpit."""

import asyncio
import hashlib
import json
import re
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from testcontainers.core.container import DockerContainer

from tests.integration.api import api_client
from tests.integration.conftest import Database
from tests.integration.evaluation import Station, incidents
from tests.integration.factories import (
    add_level,
    create_contact,
    create_graph,
    create_group,
    create_rule,
    link_station,
)
from tests.support.tokens import TokenFactory
from vigia.alerts.application.dispatch import DeliveryError, EmailDispatcher
from vigia.alerts.domain.alerts import Channel
from vigia.alerts.domain.email import EmailContent
from vigia.alerts.infrastructure.sql_dispatch import SqlDispatchQueue
from vigia.shared.clock import FakeClock, SystemClock
from vigia.shared.config import Settings
from vigia.shared.db import create_engine
from vigia.workers.dispatcher import run_dispatcher

pytestmark = pytest.mark.integration

MAILPIT_IMAGE = "axllent/mailpit:v1.31.2"  # the same version as docker-compose.yml
GT_35_ONCE = {"operator": "gt", "value": 3.5, "consecutive": 1}


@dataclass(frozen=True)
class Mailpit:
    smtp_host: str
    smtp_port: int
    api: str

    def messages_to(self, address: str) -> list[dict[str, Any]]:
        response = httpx2.get(f"{self.api}/api/v1/messages", params={"limit": 500})
        return [
            m for m in response.json()["messages"] if address in {to["Address"] for to in m["To"]}
        ]

    def text_of(self, message_id: str) -> str:
        text: str = httpx2.get(f"{self.api}/api/v1/message/{message_id}").json()["Text"]
        return text


@pytest.fixture(scope="module")
def mailpit() -> Iterator[Mailpit]:
    with DockerContainer(MAILPIT_IMAGE).with_exposed_ports(1025, 8025) as container:
        host = container.get_container_host_ip()
        api = f"http://{host}:{container.get_exposed_port(8025)}"
        for _ in range(100):
            try:
                if httpx2.get(f"{api}/readyz").status_code == 200:
                    break
            except httpx2.HTTPError:
                pass
            time.sleep(0.2)
        yield Mailpit(host, int(container.get_exposed_port(1025)), api)


@pytest.fixture
async def engine(database: Database, owner: asyncpg.Connection) -> AsyncIterator[AsyncEngine]:
    # Shared database: the dispatcher must only see this test's alerts.
    await owner.execute("DELETE FROM ingest.evaluation_queue")
    await owner.execute("DELETE FROM core.alerts WHERE status = 'pending'")
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


async def _incident_alerting(
    engine: AsyncEngine, owner: asyncpg.Connection, *names: str
) -> tuple[Station, list[str]]:
    """Opens an incident whose level 1 emails one contact per name."""
    graph = await create_graph(owner)
    await link_station(owner, graph)
    await create_rule(owner, graph, "threshold", GT_35_ONCE, station_id=graph.station_id)
    addresses = [f"{name.lower()}.{uuid4().hex[:8]}@x.test" for name in names]
    contacts = [
        await create_contact(owner, graph, name, email=address)
        for name, address in zip(names, addresses, strict=True)
    ]
    await add_level(owner, graph, 1, (await create_group(owner, graph, *contacts), "email"))
    station = Station(engine, graph)
    await station.send(3.6)
    return station, addresses


async def _alert(owner: asyncpg.Connection, address: str) -> asyncpg.Record:
    row = await owner.fetchrow(
        "SELECT id, incident_id, status, attempts, ack_token_hash, ack_token_expires_at,"
        " sent_at, last_error FROM core.alerts WHERE destination = $1",
        address,
    )
    assert row is not None
    return row


async def _alert_events(owner: asyncpg.Connection, alert_id: UUID) -> list[dict[str, Any]]:
    rows = await owner.fetch(
        "SELECT event_type, payload FROM core.incident_events"
        " WHERE event_type IN ('alert_sent', 'alert_failed')"
        " AND payload->>'alert_id' = $1 ORDER BY id",
        str(alert_id),
    )
    return [{"type": r["event_type"]} | json.loads(r["payload"]) for r in rows]


async def test_the_worker_emails_level_one_and_the_link_confirms_it(
    engine: AsyncEngine,
    owner: asyncpg.Connection,
    database: Database,
    mailpit: Mailpit,
    tmp_path: Path,
    tokens: TokenFactory,
) -> None:
    settings = Settings(
        database_url=database.app_url,
        heartbeat_dir=tmp_path,
        smtp_host=mailpit.smtp_host,
        smtp_port=mailpit.smtp_port,
        public_url="http://vigia.test",
    )
    stop = asyncio.Event()
    # Polls every 60 s, so if the email arrives right away the NOTIFY woke it up.
    worker = asyncio.create_task(run_dispatcher(settings, stop, poll_interval_s=60.0))
    await asyncio.sleep(0.5)
    try:
        station, (ana, caro) = await _incident_alerting(engine, owner, "Ana", "Caro")
        deadline = asyncio.get_running_loop().time() + 10
        while not (mailpit.messages_to(ana) and mailpit.messages_to(caro)):
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("the emails did not reach Mailpit")
            await asyncio.sleep(0.1)
    finally:
        stop.set()
        await worker

    [message] = mailpit.messages_to(ana)
    assert message["Subject"] == "[Vigía] ADVERTENCIA · Valor fuera de límite en Zona (EST-1)"
    text = mailpit.text_of(message["ID"])
    assert "Hola Ana:" in text
    assert "Valor:     3.6 m3/s" in text
    match = re.search(r"http://vigia\.test/confirmar/([A-Za-z0-9_-]{43})", text)
    assert match is not None

    alert = await _alert(owner, ana)
    # The link works: its token matches the stored hash, valid for 24 h.
    assert alert["ack_token_hash"] == hashlib.sha256(match.group(1).encode()).hexdigest()
    assert alert["ack_token_expires_at"] - alert["sent_at"] == pytest.approx(
        timedelta(hours=24), abs=timedelta(seconds=5)
    )
    assert (alert["status"], alert["attempts"]) == ("sent", 1)
    [incident] = await incidents(owner, station.graph)
    events = await _alert_events(owner, alert["id"])
    assert [(e["type"], e["attempt"]) for e in events] == [("alert_sent", 1)]
    # Neither the email nor the address ends up in the timeline.
    timeline = await owner.fetch(
        "SELECT payload::text AS p FROM core.incident_events WHERE incident_id = $1",
        incident["id"],
    )
    assert all("@" not in r["p"] for r in timeline)

    # VIG-23 end to end: the link delivered to Mailpit acknowledges the incident.
    async with api_client(database, tokens) as client:
        page = await client.get(f"/confirmar/{match.group(1)}")
        confirmed = await client.post(f"/confirmar/{match.group(1)}")
    assert (page.status_code, "Confirmar que lo vi" in page.text) == (200, True)
    assert (confirmed.status_code, "Confirmaste la alerta" in confirmed.text) == (200, True)
    [incident] = await incidents(owner, station.graph)
    assert incident["status"] == "acknowledged"


class FailsTwice:
    """Simulated channel that fails twice and then delivers (SPEC: reliability NFR)."""

    def __init__(self, failures: int = 2) -> None:
        self.failures = failures
        self.calls = 0

    async def send(self, to: str, content: EmailContent) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise DeliveryError("SMTPServerDisconnected")


async def test_a_channel_failing_twice_delivers_on_the_third_attempt(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    _, (ana,) = await _incident_alerting(engine, owner, "Ana")
    clock = FakeClock(SystemClock().now() + timedelta(seconds=1))
    dispatcher = EmailDispatcher(SqlDispatchQueue(engine), FailsTwice(), clock, "http://x")

    await dispatcher.dispatch(10)  # attempt 1: fails, retry in 5 s
    await dispatcher.dispatch(10)  # not due yet: does nothing
    clock.advance(timedelta(seconds=5))
    await dispatcher.dispatch(10)  # attempt 2: fails, retry in 10 s
    clock.advance(timedelta(seconds=10))
    await dispatcher.dispatch(10)  # attempt 3: delivers

    alert = await _alert(owner, ana)
    assert (alert["status"], alert["attempts"], alert["last_error"]) == ("sent", 3, None)
    events = await _alert_events(owner, alert["id"])
    assert [(e["type"], e["attempt"], e.get("final")) for e in events] == [
        ("alert_failed", 1, False),
        ("alert_failed", 2, False),
        ("alert_sent", 3, None),
    ]
    assert events[0]["error"] == "SMTPServerDisconnected"


async def test_after_three_retries_the_alert_is_failed_for_good(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    _, (ana,) = await _incident_alerting(engine, owner, "Ana")
    clock = FakeClock(SystemClock().now() + timedelta(seconds=1))
    dispatcher = EmailDispatcher(SqlDispatchQueue(engine), FailsTwice(99), clock, "http://x")

    for wait in (0, 5, 10, 20, 60):  # the last one finds nothing left to retry
        clock.advance(timedelta(seconds=wait))
        await dispatcher.dispatch(10)

    alert = await _alert(owner, ana)
    assert (alert["status"], alert["attempts"]) == ("failed", 4)
    events = await _alert_events(owner, alert["id"])
    assert [(e["attempt"], e["final"]) for e in events] == [
        (1, False),
        (2, False),
        (3, False),
        (4, True),
    ]


async def test_a_dispatcher_that_dies_mid_send_leaves_the_alert_for_a_retry(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    _, (ana,) = await _incident_alerting(engine, owner, "Ana")
    clock = FakeClock(SystemClock().now() + timedelta(seconds=1))
    queue = SqlDispatchQueue(engine)

    # It claimed the alert and died before recording a result.
    [claimed] = await queue.claim(
        Channel.EMAIL, clock.now(), clock.now() + timedelta(seconds=60), 10
    )
    assert claimed.destination == ana

    delivered = FailsTwice(0)
    dispatcher = EmailDispatcher(queue, delivered, clock, "http://x")
    await dispatcher.dispatch(10)
    assert delivered.calls == 0  # still claimed: nobody else sends it
    clock.advance(timedelta(seconds=61))
    await dispatcher.dispatch(10)  # the claim expired: it is retried

    alert = await _alert(owner, ana)
    assert (alert["status"], alert["attempts"], delivered.calls) == ("sent", 2, 1)


async def test_an_alert_whose_every_attempt_died_ends_failed(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    _, (ana,) = await _incident_alerting(engine, owner, "Ana")
    clock = FakeClock(SystemClock().now() + timedelta(seconds=1))
    queue = SqlDispatchQueue(engine)
    for _ in range(4):  # four claims without a result: the worker died every time
        await queue.claim(Channel.EMAIL, clock.now(), clock.now() + timedelta(seconds=60), 10)
        clock.advance(timedelta(seconds=61))

    never = FailsTwice(0)
    await EmailDispatcher(queue, never, clock, "http://x").dispatch(10)

    alert = await _alert(owner, ana)
    assert (alert["status"], alert["attempts"], never.calls) == ("failed", 4, 0)
    [event] = await _alert_events(owner, alert["id"])
    assert (event["type"], event["final"], event["error"]) == (
        "alert_failed",
        True,
        "el envío no terminó (el worker se detuvo)",
    )


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (
            "status = 'acknowledged', acknowledged_at = now(), acknowledged_by_contact_id ="
            " (SELECT contact_id FROM core.alerts WHERE incident_id = core.incidents.id LIMIT 1)",
            "el incidente ya fue confirmado",
        ),
        (
            "status = 'resolved', resolved_at = now(), resolution = 'false_alarm'",
            "el incidente ya fue resuelto",
        ),
    ],
    ids=["acknowledged", "resolved"],
)
async def test_pending_alerts_of_a_handled_incident_are_not_sent(
    engine: AsyncEngine, owner: asyncpg.Connection, change: str, reason: str
) -> None:
    station, (ana, caro) = await _incident_alerting(engine, owner, "Ana", "Caro")
    [incident] = await incidents(owner, station.graph)
    await owner.execute(f"UPDATE core.incidents SET {change} WHERE id = $1", incident["id"])

    sender = FailsTwice(0)
    clock = FakeClock(SystemClock().now() + timedelta(seconds=1))
    await EmailDispatcher(SqlDispatchQueue(engine), sender, clock, "http://x").dispatch(10)

    assert sender.calls == 0
    for address in (ana, caro):
        assert (await _alert(owner, address))["status"] == "skipped"
    skipped = await owner.fetch(
        "SELECT payload->>'reason' AS reason FROM core.incident_events"
        " WHERE incident_id = $1 AND event_type = 'alert_skipped'",
        incident["id"],
    )
    assert [r["reason"] for r in skipped] == [reason, reason]
