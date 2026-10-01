"""VIG-19: reading, acknowledging and resolving incidents against the real app and Postgres."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx2
import pytest
from uuid_utils.compat import uuid7

from tests.integration.api import api_client, bearer
from tests.integration.conftest import Database
from tests.support.tokens import (
    ISOLATION,
    RIMAC,
    SUB_ISOLATION_ADMIN,
    SUB_RIMAC_OPERATOR,
    SUB_RIMAC_RESPONDER,
    SUB_RIMAC_VIEWER,
    TokenFactory,
)
from vigia.seed import data
from vigia.shared.clock import SystemClock

pytestmark = pytest.mark.integration

DROP_RULE = data.RULES[0]  # discharge drop downstream on the Rímac


@pytest.fixture
async def client(database: Database, tokens: TokenFactory) -> AsyncIterator[httpx2.AsyncClient]:
    async with api_client(database, tokens) as client:
        yield client


def _as(tokens: TokenFactory, sub: UUID, role: str, organization: Any = RIMAC) -> dict[str, str]:
    return bearer(tokens.issue(sub, organization=organization, roles=(role,)))


@pytest.fixture
def responder(tokens: TokenFactory) -> dict[str, str]:
    return _as(tokens, SUB_RIMAC_RESPONDER, "responder")


@pytest.fixture
def operator(tokens: TokenFactory) -> dict[str, str]:
    return _as(tokens, SUB_RIMAC_OPERATOR, "operator")


@pytest.fixture
def viewer(tokens: TokenFactory) -> dict[str, str]:
    return _as(tokens, SUB_RIMAC_VIEWER, "viewer")


async def _incident(owner: asyncpg.Connection, opened_at: datetime | None = None) -> str:
    """An open incident in the seed's Rímac organization, with its `opened` event.

    By default it was opened an hour ago, so the events the API adds (at the real time)
    come after it in the timeline, which is ordered by occurred_at.
    """
    opened_at = opened_at or SystemClock().now() - timedelta(hours=1)
    incident_id = uuid7()
    await owner.execute(
        """
        INSERT INTO core.incidents (id, organization_id, zone_id, rule_id, station_id,
                                    severity, trigger_value, dedup_key, opened_at,
                                    level_started_at)
        VALUES ($1, $2, $3, $4, $5, 'critical', 34.2, $6, $7, $7)
        """,
        incident_id, data.RIMAC.id, DROP_RULE.zone_id, DROP_RULE.id, DROP_RULE.station_id,
        f"test:{uuid4()}", opened_at,
    )  # fmt: skip
    await owner.execute(
        "INSERT INTO core.incident_events (incident_id, organization_id, occurred_at,"
        " event_type, actor_type) VALUES ($1, $2, $3, 'opened', 'system')",
        incident_id, data.RIMAC.id, opened_at,
    )  # fmt: skip
    return str(incident_id)


async def _post(
    client: httpx2.AsyncClient, incident_id: str, action: str, headers: dict[str, str], **body: Any
) -> httpx2.Response:
    return await client.post(
        f"/v1/incidents/{incident_id}/{action}", json=body or None, headers=headers
    )


async def test_a_responder_acknowledges_and_the_timeline_says_who(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, responder: dict[str, str]
) -> None:
    incident_id = await _incident(owner)
    response = await _post(client, incident_id, "acknowledge", responder)

    assert response.status_code == 200, response.text
    incident = response.json()
    assert incident["status"] == "acknowledged"
    assert incident["acknowledged_by_user_id"] == str(SUB_RIMAC_RESPONDER)
    assert incident["acknowledged_by_contact_id"] is None  # CHECK: exactly one
    assert (incident["zone_name"], incident["station_code"]) == ("Chosica", "RIM-CHA-01")

    detail = (await client.get(f"/v1/incidents/{incident_id}", headers=responder)).json()
    assert [(e["event_type"], e["actor_type"], e["actor_id"]) for e in detail["timeline"]] == [
        ("opened", "system", None),
        ("acknowledged", "user", str(SUB_RIMAC_RESPONDER)),
    ]


async def test_an_operator_resolves_an_open_incident_as_a_false_alarm(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, operator: dict[str, str]
) -> None:
    incident_id = await _incident(owner)
    response = await _post(client, incident_id, "resolve", operator, resolution="false_alarm")

    assert response.status_code == 200, response.text
    incident = response.json()
    assert (incident["status"], incident["resolution"]) == ("resolved", "false_alarm")
    assert incident["resolved_at"] is not None
    assert incident["acknowledged_by_user_id"] is None  # resolving does not acknowledge

    detail = (await client.get(f"/v1/incidents/{incident_id}", headers=operator)).json()
    resolved = detail["timeline"][-1]
    assert (resolved["event_type"], resolved["payload"]) == (
        "resolved",
        {"resolution": "false_alarm", "previous_status": "open"},
    )


async def test_invalid_transitions_get_409(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, operator: dict[str, str]
) -> None:
    incident_id = await _incident(owner)
    assert (await _post(client, incident_id, "acknowledge", operator)).status_code == 200
    again = await _post(client, incident_id, "acknowledge", operator)
    assert again.status_code == 409
    assert again.json()["detail"] == "El incidente ya está confirmado: no se puede confirmar."

    assert (
        await _post(client, incident_id, "resolve", operator, resolution="resolved")
    ).status_code == 200
    for action, body in (("acknowledge", {}), ("resolve", {"resolution": "false_alarm"})):
        assert (await _post(client, incident_id, action, operator, **body)).status_code == 409


async def test_each_transition_needs_its_permission(
    client: httpx2.AsyncClient,
    owner: asyncpg.Connection,
    viewer: dict[str, str],
    responder: dict[str, str],
) -> None:
    incident_id = await _incident(owner)
    assert (await _post(client, incident_id, "acknowledge", viewer)).status_code == 403
    resolve = await _post(client, incident_id, "resolve", responder, resolution="resolved")
    assert resolve.status_code == 403
    # Anyone can view it, and nothing changed.
    detail = await client.get(f"/v1/incidents/{incident_id}", headers=viewer)
    assert (detail.status_code, detail.json()["status"]) == (200, "open")


async def test_another_organization_gets_404(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, tokens: TokenFactory
) -> None:
    incident_id = await _incident(owner)
    admin = _as(tokens, SUB_ISOLATION_ADMIN, "admin", organization=ISOLATION)

    assert (await client.get(f"/v1/incidents/{incident_id}", headers=admin)).status_code == 404
    assert (await _post(client, incident_id, "acknowledge", admin)).status_code == 404
    resolve = await _post(client, incident_id, "resolve", admin, resolution="resolved")
    assert resolve.status_code == 404
    listed = (await client.get("/v1/incidents", headers=admin)).json()
    assert incident_id not in {i["id"] for i in listed}
    # Nothing changed: neither the status nor the timeline.
    row = await owner.fetchrow(
        "SELECT i.status, (SELECT count(*) FROM core.incident_events e"
        " WHERE e.incident_id = i.id) AS events FROM core.incidents i WHERE i.id = $1",
        UUID(incident_id),
    )
    assert row is not None
    assert (row["status"], row["events"]) == ("open", 1)


async def test_the_list_filters_by_status_and_shows_the_newest_first(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, operator: dict[str, str]
) -> None:
    # In the far future, so they come first even if the shared database has other incidents.
    base = datetime(2090, 1, 1, tzinfo=UTC) + timedelta(minutes=uuid4().int % 100_000)
    oldest, middle, newest = [
        await _incident(owner, base + timedelta(minutes=m)) for m in (0, 1, 2)
    ]
    await _post(client, middle, "acknowledge", operator)
    await _post(client, newest, "resolve", operator, resolution="resolved")

    everything = await client.get("/v1/incidents", params={"limit": 3}, headers=operator)
    assert [i["id"] for i in everything.json()] == [newest, middle, oldest]

    active = await client.get(
        "/v1/incidents", params=[("status", "open"), ("status", "acknowledged")], headers=operator
    )
    ids = [i["id"] for i in active.json()]
    assert newest not in ids
    assert ids.index(middle) < ids.index(oldest)


async def test_an_unknown_resolution_gets_422(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, operator: dict[str, str]
) -> None:
    incident_id = await _incident(owner)
    response = await _post(client, incident_id, "resolve", operator, resolution="solved")
    assert response.status_code == 422


async def test_two_operators_resolving_at_once_get_one_200_and_one_409(
    database: Database, owner: asyncpg.Connection, tokens: TokenFactory, operator: dict[str, str]
) -> None:
    incident_id = await _incident(owner)
    # Two API replicas, each with its own pool, sharing only the database.
    async with api_client(database, tokens) as first, api_client(database, tokens) as second:
        responses = await asyncio.gather(
            _post(first, incident_id, "resolve", operator, resolution="resolved"),
            _post(second, incident_id, "resolve", operator, resolution="false_alarm"),
        )

    assert sorted(r.status_code for r in responses) == [200, 409]
    resolved_events = await owner.fetchval(
        "SELECT count(*) FROM core.incident_events WHERE incident_id = $1"
        " AND event_type = 'resolved'",
        UUID(incident_id),
    )
    assert resolved_events == 1
