"""VIG-36: contact groups CRUD against the real app and Postgres: permissions per role, audit,
members, the policies that block a delete, and isolation."""

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx2
import pytest

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

pytestmark = pytest.mark.integration

URL = "/v1/contact-groups"


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
    body.setdefault("name", f"Grupo {uuid4().hex[:6]}")
    response = await client.post(URL, json=body, headers=admin)
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
    assert (await client.get(URL, headers=headers)).status_code == reads
    name = f"Grupo {uuid4().hex[:6]}"
    assert (await client.post(URL, json={"name": name}, headers=headers)).status_code == writes


async def test_a_group_shows_its_zone_members_and_the_policies_that_notify_it(
    client: httpx2.AsyncClient, admin: dict[str, str]
) -> None:
    brigade = (await client.get(f"{URL}/{data.G_BRIGADE}", headers=admin)).json()
    assert brigade["zone"] == {"id": str(data.Z_CHOSICA), "name": "Chosica"}
    names = [m["name"] for m in brigade["members"]]
    assert {"Rosa Brigada", "Lucho Quispe (líder comunal, Quirio)"} <= set(names)
    assert names == sorted(names)
    assert brigade["policies"] == [{"id": str(data.P_RIMAC), "name": "Protocolo Rímac"}]


async def test_a_group_is_created_edited_and_deleted_with_its_audit(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, admin: dict[str, str]
) -> None:
    name = f"Vecinos {uuid4().hex[:6]}"
    group = await _create(
        client, admin, name=f"  {name} ", zone_id=str(data.Z_CHACLACAYO),
        member_ids=[str(data.C_BRIGADE), str(data.C_HEADQUARTERS)],
    )  # fmt: skip
    assert group["name"] == name
    assert [m["name"] for m in group["members"]] == ["Carmen Jefatura COE", "Rosa Brigada"]
    assert group["policies"] == []

    # The contacts API sees the new membership too.
    rosa = (await client.get(f"/v1/contacts/{data.C_BRIGADE}", headers=admin)).json()
    assert name in [g["name"] for g in rosa["groups"]]

    url = f"{URL}/{group['id']}"
    edited = await client.put(
        url, json={"name": name, "member_ids": [str(data.C_OPERATOR)]}, headers=admin
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["zone"] is None
    assert [m["name"] for m in edited.json()["members"]] == ["Óscar Operador"]

    assert (await client.delete(url, headers=admin)).status_code == 204
    assert (await client.get(url, headers=admin)).status_code == 404

    rows = await owner.fetch(
        "SELECT action, before, after FROM core.audit_log"
        " WHERE entity_type = 'contact_group' AND entity_id = $1 ORDER BY id",
        UUID(group["id"]),
    )
    assert [r["action"] for r in rows] == ["create", "update", "delete"]
    created, edited_after = (json.loads(r["after"]) for r in rows[:2])
    assert created["zone"] == "Chaclacayo"
    assert edited_after == {"name": name, "zone": None, "members": ["Óscar Operador"]}


async def test_a_duplicate_name_gets_409(client: httpx2.AsyncClient, admin: dict[str, str]) -> None:
    response = await client.post(URL, json={"name": "Brigada Chosica"}, headers=admin)
    assert response.status_code == 409
    assert response.json()["detail"] == "Ya hay un grupo con ese nombre."


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"name": "   "}, "name"),
        ({"name": "Ajeno", "zone_id": str(data.Z_TEST)}, "zone_id"),  # another organization's
        ({"name": "Ajeno", "member_ids": [str(data.C_AIS)]}, "member_ids"),
    ],
)
async def test_an_invalid_group_gets_422_on_its_field(
    client: httpx2.AsyncClient, admin: dict[str, str], body: dict[str, Any], field: str
) -> None:
    response = await client.post(URL, json=body, headers=admin)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", field]


async def test_a_group_a_policy_notifies_gets_409_naming_the_policy(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, admin: dict[str, str]
) -> None:
    refused = await client.delete(f"{URL}/{data.G_BRIGADE}", headers=admin)
    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "Brigada Chosica se usa en «Protocolo Rímac». Quítalo de esa política antes de borrarlo."
    )
    members = await owner.fetchval(
        "SELECT count(*) FROM core.contact_group_members WHERE group_id = $1", data.G_BRIGADE
    )
    assert members >= 2  # untouched


async def test_another_organization_never_sees_or_touches_these_groups(
    client: httpx2.AsyncClient, tokens: TokenFactory, admin: dict[str, str]
) -> None:
    group = await _create(client, admin)
    other = _as(tokens, SUB_ISOLATION_ADMIN, "admin", organization=ISOLATION)
    listing = await client.get(URL, headers=other)
    assert group["id"] not in listing.text
    assert "Brigada Chosica" not in listing.text
    url = f"{URL}/{group['id']}"
    assert (await client.get(url, headers=other)).status_code == 404
    assert (await client.put(url, json={"name": "x"}, headers=other)).status_code == 404
    assert (await client.delete(url, headers=other)).status_code == 404
