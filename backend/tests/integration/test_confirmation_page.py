"""VIG-23: the confirmation page against the real app and Postgres."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID

import asyncpg
import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

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
from willay.alerts.domain.delivery import new_ack_token
from willay.shared.clock import SystemClock
from willay.shared.db import create_engine

pytestmark = pytest.mark.integration

GT_35_ONCE = {"operator": "gt", "value": 3.5, "consecutive": 1}


@pytest.fixture
async def engine(database: Database, owner: asyncpg.Connection) -> AsyncIterator[AsyncEngine]:
    await owner.execute("DELETE FROM ingest.evaluation_queue")  # shared database
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def client(database: Database, tokens: TokenFactory) -> AsyncIterator[httpx2.AsyncClient]:
    async with api_client(database, tokens) as client:
        yield client


class Case:
    """An open incident with an alert sent to each contact, each with its token."""

    def __init__(self, incident_id: UUID, contacts: dict[str, UUID], links: dict[str, str]):
        self.incident_id, self.contacts, self.links = incident_id, contacts, links


async def _case(
    engine: AsyncEngine, owner: asyncpg.Connection, *names: str, expired: bool = False
) -> Case:
    graph = await create_graph(owner)
    await link_station(owner, graph)
    await create_rule(owner, graph, "threshold", GT_35_ONCE, station_id=graph.station_id)
    contacts = {
        name: await create_contact(owner, graph, name, email=f"{name}@x.test") for name in names
    }
    await add_level(
        owner, graph, 1, (await create_group(owner, graph, *contacts.values()), "email")
    )
    station = Station(engine, graph)
    await station.send(3.6)
    [incident] = await incidents(owner, station.graph)

    now = SystemClock().now()
    links = {}
    for name, contact_id in contacts.items():
        token = new_ack_token(now - timedelta(hours=25) if expired else now)
        # As if the dispatcher had sent it with this token.
        await owner.execute(
            "UPDATE core.alerts SET status = 'sent', sent_at = $1, ack_token_hash = $2,"
            " ack_token_expires_at = $3 WHERE incident_id = $4 AND contact_id = $5",
            now, token.token_hash, token.expires_at, incident["id"], contact_id,
        )  # fmt: skip
        links[name] = f"/confirmar/{token.token}"
    return Case(incident["id"], contacts, links)


async def _state(owner: asyncpg.Connection, case: Case) -> asyncpg.Record:
    row = await owner.fetchrow(
        "SELECT status, acknowledged_by_contact_id, acknowledged_by_user_id,"
        " (SELECT count(*) FROM core.incident_events e WHERE e.incident_id = i.id) AS events"
        " FROM core.incidents i WHERE id = $1",
        case.incident_id,
    )
    assert row is not None
    return row


async def _alert_status(owner: asyncpg.Connection, case: Case, name: str) -> str:
    status: str = await owner.fetchval(
        "SELECT status FROM core.alerts WHERE incident_id = $1 AND contact_id = $2",
        case.incident_id,
        case.contacts[name],
    )
    return status


async def test_opening_the_link_shows_the_incident_and_changes_nothing(
    engine: AsyncEngine, owner: asyncpg.Connection, client: httpx2.AsyncClient
) -> None:
    case = await _case(engine, owner, "Ana")
    before = await _state(owner, case)

    for _ in range(2):  # an email scanner, then the person
        page = await client.get(case.links["Ana"])
        assert page.status_code == 200
    html = page.text
    assert "Hola Ana:" in html
    assert "<dt>Causa</dt><dd>Valor fuera de límite</dd>" in html
    assert "<dt>Valor</dt><dd>3.6 m3/s</dd>" in html
    assert '<form method="post"><button type="submit">Confirmar que lo vi</button>' in html
    # The token is in the URL: no Referer, caching or indexing; no scripts.
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in page.headers["content-security-policy"]
    # Without login, the device is the only signal for dark mode (VIG-41).
    assert "@media (prefers-color-scheme: dark)" in html

    assert await _state(owner, case) == before
    assert await _alert_status(owner, case, "Ana") == "sent"


async def test_the_button_confirms_the_incident_as_the_contact_once(
    engine: AsyncEngine, owner: asyncpg.Connection, client: httpx2.AsyncClient
) -> None:
    case = await _case(engine, owner, "Ana")
    response = await client.post(case.links["Ana"])

    assert response.status_code == 200
    assert "Confirmaste la alerta" in response.text
    state = await _state(owner, case)
    assert (state["status"], state["acknowledged_by_contact_id"]) == (
        "acknowledged",
        case.contacts["Ana"],
    )
    assert state["acknowledged_by_user_id"] is None
    event = await owner.fetchrow(
        "SELECT actor_type, actor_id FROM core.incident_events"
        " WHERE incident_id = $1 AND event_type = 'acknowledged'",
        case.incident_id,
    )
    assert event is not None
    assert (event["actor_type"], event["actor_id"]) == ("contact", case.contacts["Ana"])
    assert await _alert_status(owner, case, "Ana") == "acknowledged"

    # Single use: the second click and the link no longer work.
    again = await client.post(case.links["Ana"])
    assert (again.status_code, "ya se usó" in again.text) == (410, True)
    assert (await client.get(case.links["Ana"])).status_code == 410


async def test_a_late_contact_is_recorded_as_having_seen_it(
    engine: AsyncEngine, owner: asyncpg.Connection, client: httpx2.AsyncClient
) -> None:
    case = await _case(engine, owner, "Ana", "Caro")
    await client.post(case.links["Ana"])

    page = await client.get(case.links["Caro"])
    assert "Ana ya lo había confirmado el" in page.text
    assert "Registrar que lo vi" in page.text
    result = await client.post(case.links["Caro"])

    assert result.status_code == 200
    assert "quedó registrado que la viste" in result.text
    state = await _state(owner, case)
    assert state["acknowledged_by_contact_id"] == case.contacts["Ana"]  # still Ana
    assert await _alert_status(owner, case, "Caro") == "acknowledged"


async def test_a_resolved_incident_is_not_confirmed(
    engine: AsyncEngine, owner: asyncpg.Connection, client: httpx2.AsyncClient
) -> None:
    case = await _case(engine, owner, "Ana")
    await owner.execute(
        "UPDATE core.incidents SET status = 'resolved', resolved_at = now(),"
        " resolution = 'false_alarm' WHERE id = $1",
        case.incident_id,
    )
    before = await _state(owner, case)

    assert "ya fue resuelto" in (await client.get(case.links["Ana"])).text
    response = await client.post(case.links["Ana"])

    assert (response.status_code, "ya fue resuelto" in response.text) == (200, True)
    assert await _state(owner, case) == before
    assert await _alert_status(owner, case, "Ana") == "sent"


async def test_expired_and_unknown_links(
    engine: AsyncEngine, owner: asyncpg.Connection, client: httpx2.AsyncClient
) -> None:
    case = await _case(engine, owner, "Ana", expired=True)
    expired = await client.post(case.links["Ana"])
    unknown = await client.get("/confirmar/" + "x" * 43)

    assert (expired.status_code, "venció" in expired.text) == (410, True)
    assert (unknown.status_code, "Enlace no válido" in unknown.text) == (404, True)
    assert (await _state(owner, case))["status"] == "open"


async def test_the_page_speaks_the_language_of_the_contact(
    engine: AsyncEngine, owner: asyncpg.Connection, client: httpx2.AsyncClient
) -> None:
    case = await _case(engine, owner, "Ana", "Caro")
    await owner.execute(
        "UPDATE core.contacts SET language = 'en' WHERE id = $1", case.contacts["Ana"]
    )
    # Whatever the browser says: the contact chose English.
    page = await client.get(case.links["Ana"], headers={"Accept-Language": "es-PE"})
    assert page.headers["content-language"] == "en"
    assert '<html lang="en">' in page.text
    assert "Hello Ana," in page.text
    assert "<dt>Cause</dt><dd>Value out of bounds</dd>" in page.text
    assert '<button type="submit">Acknowledge: I saw it</button>' in page.text
    assert "Thank you! You acknowledged the alert" in (await client.post(case.links["Ana"])).text

    # Caro chose none, so she gets her organization's language.
    await owner.execute(
        "UPDATE core.organizations SET language = 'en'"
        " WHERE id = (SELECT organization_id FROM core.contacts WHERE id = $1)",
        case.contacts["Caro"],
    )
    late = await client.get(case.links["Caro"])
    assert "Ana had already acknowledged it on" in late.text


async def test_a_link_of_no_alert_follows_the_browser(client: httpx2.AsyncClient) -> None:
    unknown = await client.get("/confirmar/" + "x" * 43, headers={"Accept-Language": "en-US"})
    assert (unknown.status_code, unknown.headers["content-language"]) == (404, "en")
    assert "<h1>Invalid link</h1>" in unknown.text


async def test_names_are_escaped(
    engine: AsyncEngine, owner: asyncpg.Connection, client: httpx2.AsyncClient
) -> None:
    case = await _case(engine, owner, "<script>alert(1)</script>")
    html = (await client.get(case.links["<script>alert(1)</script>"])).text
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


async def test_two_clicks_at_once_confirm_only_once(
    engine: AsyncEngine, owner: asyncpg.Connection, database: Database, tokens: TokenFactory
) -> None:
    case = await _case(engine, owner, "Ana")
    # Two API replicas: the double click reaches two different processes.
    async with api_client(database, tokens) as first, api_client(database, tokens) as second:
        responses = await asyncio.gather(
            first.post(case.links["Ana"]), second.post(case.links["Ana"])
        )
    assert sorted(r.status_code for r in responses) == [200, 410]
    acknowledged = await owner.fetchval(
        "SELECT count(*) FROM core.incident_events WHERE incident_id = $1"
        " AND event_type = 'acknowledged'",
        case.incident_id,
    )
    assert acknowledged == 1
