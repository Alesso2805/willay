"""VIG-44: the organization's settings against the real app and Postgres: every role reads,
only an admin changes, the change is audited, reaches /v1/me and stays in its organization."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

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
    SUB_RIMAC_VIEWER,
    TokenFactory,
)
from willay.seed import data

pytestmark = pytest.mark.integration

URL = "/v1/organization"


@pytest.fixture
async def client(
    database: Database, tokens: TokenFactory, owner: asyncpg.Connection
) -> AsyncIterator[httpx2.AsyncClient]:
    async with api_client(database, tokens) as client:
        yield client
    # Other tests read the seed's organizations as the seed made them.
    for organization in data.ORGANIZATIONS:
        await owner.execute(
            "UPDATE core.organizations SET language = 'es', timezone = $2 WHERE id = $1",
            organization.id,
            organization.timezone,
        )


def _as(tokens: TokenFactory, sub: UUID, role: str, organization: Any = RIMAC) -> dict[str, str]:
    return bearer(tokens.issue(sub, organization=organization, roles=(role,)))


async def test_every_role_reads_its_organization(
    client: httpx2.AsyncClient, tokens: TokenFactory
) -> None:
    response = await client.get(URL, headers=_as(tokens, SUB_RIMAC_VIEWER, "viewer"))
    assert response.status_code == 200
    assert response.json() == {
        "id": str(data.RIMAC.id),
        "name": "Demo Rímac",
        "language": "es",
        "timezone": "America/Lima",
    }


async def test_an_admin_changes_it_audited_and_the_session_follows(
    client: httpx2.AsyncClient, tokens: TokenFactory, owner: asyncpg.Connection
) -> None:
    admin = _as(tokens, SUB_RIMAC_ADMIN, "admin")
    body = {"language": "en", "timezone": "America/Bogota"}
    response = await client.put(URL, json=body, headers=admin)

    assert response.status_code == 200
    assert (response.json()["language"], response.json()["timezone"]) == ("en", "America/Bogota")
    me = (await client.get("/v1/me", headers=admin)).json()
    assert me["organization_timezone"] == "America/Bogota"
    audit = await owner.fetchrow(
        "SELECT actor_id, action, before, after FROM core.audit_log"
        " WHERE entity_type = 'organization' AND organization_id = $1 ORDER BY id DESC LIMIT 1",
        data.RIMAC.id,
    )
    assert audit is not None
    assert (audit["actor_id"], audit["action"]) == (SUB_RIMAC_ADMIN, "update")
    # Only this organization: the other keeps its own.
    other = await owner.fetchrow(
        "SELECT language, timezone FROM core.organizations WHERE id = $1", data.ISOLATION.id
    )
    assert other is not None
    assert (other["language"], other["timezone"]) == ("es", "America/Lima")


async def test_only_an_admin_changes_it(client: httpx2.AsyncClient, tokens: TokenFactory) -> None:
    body = {"language": "en", "timezone": "America/Bogota"}
    operator = _as(tokens, SUB_RIMAC_OPERATOR, "operator")
    response = await client.put(URL, json=body, headers=operator)
    assert (response.status_code, response.json()["code"]) == (403, "permission_denied")


async def test_a_time_zone_must_be_an_iana_name(
    client: httpx2.AsyncClient, tokens: TokenFactory
) -> None:
    admin = _as(tokens, SUB_ISOLATION_ADMIN, "admin", ISOLATION)
    response = await client.put(
        URL,
        json={"language": "es", "timezone": "-05:00"},
        headers={**admin, "Accept-Language": "en"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "organization_timezone_unknown"
    assert body["detail"][0]["loc"] == ["body", "timezone"]
    assert "is not a known time zone" in body["detail"][0]["msg"]
    language = await client.put(URL, json={"language": "fr", "timezone": "UTC"}, headers=admin)
    assert language.status_code == 422
