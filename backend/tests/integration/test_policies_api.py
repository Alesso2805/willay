"""VIG-24: CRUD de políticas de escalamiento contra la app y Postgres reales."""

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
    AISLAMIENTO,
    RIMAC,
    SUB_AISLAMIENTO_ADMIN,
    SUB_RIMAC_ADMIN,
    SUB_RIMAC_OPERATOR,
    SUB_RIMAC_VIEWER,
    TokenFactory,
)
from vigia.seed import data

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(database: Database, tokens: TokenFactory) -> AsyncIterator[httpx2.AsyncClient]:
    async with api_client(database, tokens) as client:
        yield client


def _as(tokens: TokenFactory, sub: UUID, role: str, organization: Any = RIMAC) -> dict[str, str]:
    return bearer(tokens.issue(sub, organization=organization, roles=(role,)))


@pytest.fixture
def admin(tokens: TokenFactory) -> dict[str, str]:
    return _as(tokens, SUB_RIMAC_ADMIN, "admin")


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": f"Protocolo {uuid4().hex[:8]}",
        "levels": [
            {
                "wait_s": 120,
                "targets": [{"contact_group_id": str(data.G_OPERADORES), "channel": "email"}],
            },
            {
                "wait_s": 300,
                "targets": [
                    {"contact_group_id": str(data.G_BRIGADA), "channel": "email"},
                    {"contact_group_id": str(data.G_BRIGADA), "channel": "telegram"},
                ],
            },
        ],
    }
    return body | overrides


async def _audit(owner: asyncpg.Connection, policy_id: str) -> list[tuple[str, Any, Any]]:
    rows = await owner.fetch(
        "SELECT action, before, after FROM core.audit_log WHERE entity_id = $1 ORDER BY id",
        UUID(policy_id),
    )
    return [
        (r["action"], json.loads(r["before"] or "null"), json.loads(r["after"] or "null"))
        for r in rows
    ]


async def test_an_admin_creates_edits_and_deletes_a_policy_all_audited(
    client: httpx2.AsyncClient, admin: dict[str, str], owner: asyncpg.Connection
) -> None:
    body = _body()
    created = await client.post("/v1/escalation-policies", json=body, headers=admin)
    assert created.status_code == 201, created.text
    policy = created.json()
    assert created.headers["location"] == f"/v1/escalation-policies/{policy['id']}"
    assert [(level["level_order"], level["wait_s"]) for level in policy["levels"]] == [
        (1, 120),
        (2, 300),
    ]
    assert policy["levels"][0]["targets"] == [
        {
            "contact_group_id": str(data.G_OPERADORES),
            "contact_group_name": "Operadores de turno",
            "channel": "email",
        }
    ]

    edited_body = _body(name=body["name"], levels=body["levels"][:1])
    edited = await client.put(
        f"/v1/escalation-policies/{policy['id']}", json=edited_body, headers=admin
    )
    assert (edited.status_code, len(edited.json()["levels"])) == (200, 1)

    deleted = await client.delete(f"/v1/escalation-policies/{policy['id']}", headers=admin)
    assert deleted.status_code == 204
    missing = await client.get(f"/v1/escalation-policies/{policy['id']}", headers=admin)
    assert missing.status_code == 404

    audit = await _audit(owner, policy["id"])
    assert [action for action, _, _ in audit] == ["create", "update", "delete"]
    _, before, after = audit[1]
    assert (len(before["levels"]), len(after["levels"])) == (2, 1)


async def test_a_policy_in_use_by_rules_cannot_be_deleted(
    client: httpx2.AsyncClient, admin: dict[str, str]
) -> None:
    response = await client.delete(f"/v1/escalation-policies/{data.P_RIMAC}", headers=admin)
    assert response.status_code == 409
    assert "regla" in response.json()["detail"]
    still = await client.get(f"/v1/escalation-policies/{data.P_RIMAC}", headers=admin)
    assert [level["wait_s"] for level in still.json()["levels"]] == [120, 180, 300]


async def test_names_are_unique_per_organization(
    client: httpx2.AsyncClient, admin: dict[str, str]
) -> None:
    body = _body()
    assert (
        await client.post("/v1/escalation-policies", json=body, headers=admin)
    ).status_code == 201
    again = await client.post("/v1/escalation-policies", json=body, headers=admin)
    assert again.status_code == 409


@pytest.mark.parametrize(
    ("levels", "reason"),
    [
        ([], "invalid_policy"),
        (
            [
                {
                    "wait_s": 0,
                    "targets": [{"contact_group_id": str(data.G_OPERADORES), "channel": "email"}],
                }
            ],
            "invalid_policy",
        ),
        ([{"wait_s": 120, "targets": []}], "invalid_policy"),
        # Un grupo de otra organización no existe para esta.
        (
            [
                {
                    "wait_s": 120,
                    "targets": [
                        {"contact_group_id": str(data.G_EQUIPO_PRUEBA), "channel": "email"}
                    ],
                }
            ],
            "unknown_contact_group",
        ),
        (
            [{"wait_s": 120, "targets": [{"contact_group_id": str(uuid4()), "channel": "email"}]}],
            "unknown_contact_group",
        ),
    ],
    ids=["sin-niveles", "espera-0", "sin-destinos", "grupo-de-otra-org", "grupo-inexistente"],
)
async def test_invalid_policies_get_422(
    client: httpx2.AsyncClient, admin: dict[str, str], levels: list[Any], reason: str
) -> None:
    response = await client.post(
        "/v1/escalation-policies", json=_body(levels=levels), headers=admin
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == reason


async def test_only_admins_manage_policies_but_everyone_reads_them(
    client: httpx2.AsyncClient, tokens: TokenFactory
) -> None:
    operator = _as(tokens, SUB_RIMAC_OPERATOR, "operator")
    viewer = _as(tokens, SUB_RIMAC_VIEWER, "viewer")

    assert (
        await client.post("/v1/escalation-policies", json=_body(), headers=operator)
    ).status_code == 403
    assert (
        await client.delete(f"/v1/escalation-policies/{data.P_RIMAC}", headers=operator)
    ).status_code == 403
    listed = await client.get("/v1/escalation-policies", headers=viewer)
    assert listed.status_code == 200
    assert str(data.P_RIMAC) in {p["id"] for p in listed.json()}


async def test_another_organization_sees_nothing(
    client: httpx2.AsyncClient, tokens: TokenFactory
) -> None:
    other = _as(tokens, SUB_AISLAMIENTO_ADMIN, "admin", organization=AISLAMIENTO)
    assert (
        await client.get(f"/v1/escalation-policies/{data.P_RIMAC}", headers=other)
    ).status_code == 404
    put = await client.put(f"/v1/escalation-policies/{data.P_RIMAC}", json=_body(), headers=other)
    assert put.status_code == 404
    listed = (await client.get("/v1/escalation-policies", headers=other)).json()
    assert {p["id"] for p in listed} == {str(data.P_AISLAMIENTO)}
