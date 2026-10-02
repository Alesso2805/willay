"""VIG-36: contacts CRUD against the real app and Postgres: permissions per role, audit,
history protection, isolation, and the Telegram chat never leaving the API."""

from collections.abc import AsyncIterator
from datetime import timedelta
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
    SUB_RIMAC_ADMIN,
    SUB_RIMAC_OPERATOR,
    SUB_RIMAC_RESPONDER,
    SUB_RIMAC_VIEWER,
    TokenFactory,
)
from willay.seed import data
from willay.shared.clock import SystemClock

pytestmark = pytest.mark.integration

CHAT_ID = 777_000_123


@pytest.fixture
async def client(database: Database, tokens: TokenFactory) -> AsyncIterator[httpx2.AsyncClient]:
    async with api_client(database, tokens) as client:
        yield client


def _as(tokens: TokenFactory, sub: UUID, role: str, organization: Any = RIMAC) -> dict[str, str]:
    return bearer(tokens.issue(sub, organization=organization, roles=(role,)))


@pytest.fixture
def admin(tokens: TokenFactory) -> dict[str, str]:
    return _as(tokens, SUB_RIMAC_ADMIN, "admin")


async def _create(client: httpx2.AsyncClient, admin: dict[str, str], **body: Any) -> dict[str, Any]:
    body.setdefault("full_name", f"Contacto {uuid4().hex[:6]}")
    response = await client.post("/v1/contacts", json=body, headers=admin)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


@pytest.mark.parametrize(
    ("sub", "role", "reads", "writes"),
    [
        (SUB_RIMAC_VIEWER, "viewer", 403, 403),
        (SUB_RIMAC_RESPONDER, "responder", 403, 403),
        (SUB_RIMAC_OPERATOR, "operator", 200, 403),
        (SUB_RIMAC_ADMIN, "admin", 200, 201),
    ],
)
async def test_admin_and_operator_read_and_only_admin_writes(
    client: httpx2.AsyncClient, tokens: TokenFactory, sub: UUID, role: str, reads: int, writes: int
) -> None:
    headers = _as(tokens, sub, role)
    assert (await client.get("/v1/contacts", headers=headers)).status_code == reads
    created = await client.post("/v1/contacts", json={"full_name": "Nuevo"}, headers=headers)
    assert created.status_code == writes


async def test_a_contact_is_created_edited_and_deleted_with_its_audit(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, admin: dict[str, str]
) -> None:
    contact = await _create(client, admin, full_name="  Lucho Quispe  ", email="")
    assert contact | {"id": None} == {
        "id": None,
        "full_name": "Lucho Quispe",
        "email": None,  # an empty field means no email
        "telegram_linked": False,
        "telegram_link_expires_at": None,
        "groups": [],
        "has_history": False,
    }
    url = f"/v1/contacts/{contact['id']}"
    edited = await client.put(
        url, json={"full_name": "Lucho Quispe", "email": "lucho@quirio.pe"}, headers=admin
    )
    assert edited.json()["email"] == "lucho@quirio.pe"
    assert (await client.delete(url, headers=admin)).status_code == 204
    assert (await client.get(url, headers=admin)).status_code == 404

    actions = await owner.fetch(
        "SELECT action FROM core.audit_log WHERE entity_type = 'contact' AND entity_id = $1"
        " ORDER BY id",
        UUID(contact["id"]),
    )
    assert [r["action"] for r in actions] == ["create", "update", "delete"]


@pytest.mark.parametrize(
    ("body", "field"),
    [({"full_name": "   "}, "full_name"), ({"full_name": "Rosa", "email": "rosa@rimac"}, "email")],
)
async def test_an_invalid_contact_gets_422_on_its_field(
    client: httpx2.AsyncClient, admin: dict[str, str], body: dict[str, str], field: str
) -> None:
    response = await client.post("/v1/contacts", json=body, headers=admin)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", field]


async def test_a_contact_with_history_gets_409_and_can_be_removed_from_its_groups(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, admin: dict[str, str]
) -> None:
    contact = await _create(client, admin, email="historia@rimac.willay.test")
    contact_id = UUID(contact["id"])
    await owner.execute(
        "INSERT INTO core.contact_group_members (group_id, contact_id) VALUES ($1, $2)",
        data.G_OPERATORS, contact_id,
    )  # fmt: skip
    incident_id = uuid7()
    rule = data.RULES[0]
    now = SystemClock().now()
    await owner.execute(
        "INSERT INTO core.incidents (id, organization_id, zone_id, rule_id, station_id,"
        " severity, dedup_key, opened_at, level_started_at)"
        " VALUES ($1, $2, $3, $4, $5, 'critical', $6, $7, $7)",
        incident_id, data.RIMAC.id, rule.zone_id, rule.id, rule.station_id, f"test:{uuid4()}", now,
    )  # fmt: skip
    await owner.execute(
        "INSERT INTO core.alerts (id, incident_id, level_order, contact_id, channel, destination,"
        " status, attempts, sent_at) VALUES ($1, $2, 1, $3, 'email', $4, 'sent', 1, $5)",
        uuid7(), incident_id, contact_id, contact["email"], now,
    )  # fmt: skip

    url = f"/v1/contacts/{contact_id}"
    refused = await client.delete(url, headers=admin)
    assert refused.status_code == 409
    assert "Quítalo de sus grupos" in refused.json()["detail"]
    still = (await client.get(url, headers=admin)).json()
    assert still["has_history"] is True
    assert [g["name"] for g in still["groups"]] == ["Operadores de turno"]  # untouched

    removed = await client.post(f"{url}/remove-from-groups", headers=admin)
    assert removed.status_code == 200
    assert removed.json()["groups"] == []


async def test_telegram_is_reported_but_the_chat_never_leaves_the_api(
    client: httpx2.AsyncClient,
    owner: asyncpg.Connection,
    tokens: TokenFactory,
    admin: dict[str, str],
) -> None:
    contact = await _create(client, admin)
    contact_id = UUID(contact["id"])
    await owner.execute(
        "UPDATE core.contacts SET telegram_chat_id = $1 WHERE id = $2", CHAT_ID, contact_id
    )
    operator = _as(tokens, SUB_RIMAC_OPERATOR, "operator")
    for headers in (admin, operator):
        listing = await client.get("/v1/contacts", headers=headers)
        assert str(CHAT_ID) not in listing.text
        mine = next(c for c in listing.json() if c["id"] == str(contact_id))
        assert mine["telegram_linked"] is True

    unlinked = await client.delete(f"/v1/contacts/{contact_id}/telegram", headers=admin)
    assert unlinked.json()["telegram_linked"] is False
    assert (
        await owner.fetchval("SELECT telegram_chat_id FROM core.contacts WHERE id = $1", contact_id)
        is None
    )


async def test_a_pending_telegram_link_shows_until_it_expires(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, admin: dict[str, str]
) -> None:
    contact = await _create(client, admin)
    url = f"/v1/contacts/{contact['id']}"
    for days, shown in ((7, True), (-1, False)):
        await owner.execute(
            "UPDATE core.contacts SET telegram_link_expires_at = $1 WHERE id = $2",
            SystemClock().now() + timedelta(days=days), UUID(contact["id"]),
        )  # fmt: skip
        pending = (await client.get(url, headers=admin)).json()["telegram_link_expires_at"]
        assert (pending is not None) is shown


async def test_another_organization_never_sees_or_touches_these_contacts(
    client: httpx2.AsyncClient, tokens: TokenFactory, admin: dict[str, str]
) -> None:
    contact = await _create(client, admin)
    other = _as(tokens, SUB_ISOLATION_ADMIN, "admin", organization=ISOLATION)
    listing = await client.get("/v1/contacts", headers=other)
    assert contact["id"] not in listing.text
    url = f"/v1/contacts/{contact['id']}"
    assert (await client.get(url, headers=other)).status_code == 404
    assert (await client.put(url, json={"full_name": "x"}, headers=other)).status_code == 404
    assert (await client.delete(url, headers=other)).status_code == 404
    assert (await client.delete(f"{url}/telegram", headers=other)).status_code == 404
