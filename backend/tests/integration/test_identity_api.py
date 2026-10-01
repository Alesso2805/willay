"""VIG-06: autenticación, resolución del tenant y 401/403 contra la app y Postgres reales."""

from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from uuid import UUID

import asyncpg
import httpx2
import pytest
from uuid_utils.compat import uuid7

from tests.integration.api import api_client, bearer
from tests.integration.conftest import Database
from tests.support.tokens import (
    AISLAMIENTO,
    RIMAC,
    SUB_AISLAMIENTO_ADMIN,
    SUB_DOS_ORGS,
    SUB_RIMAC_OPERATOR,
    SUB_SIN_ORG,
    TokenFactory,
)
from vigia.seed import data

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(database: Database, tokens: TokenFactory) -> AsyncIterator[httpx2.AsyncClient]:
    async with api_client(database, tokens) as client:
        yield client


async def _me(client: httpx2.AsyncClient, token: str | None) -> httpx2.Response:
    return await client.get("/v1/me", headers=bearer(token))


async def test_each_seed_organization_sees_itself(
    client: httpx2.AsyncClient, tokens: TokenFactory
) -> None:
    rimac = await _me(client, tokens.issue(SUB_RIMAC_OPERATOR, organization=RIMAC))
    aislamiento = await _me(
        client, tokens.issue(SUB_AISLAMIENTO_ADMIN, organization=AISLAMIENTO, roles=("admin",))
    )

    assert rimac.status_code == 200, rimac.text
    assert rimac.json()["organization_id"] == str(data.RIMAC.id)
    assert rimac.json()["organization_name"] == "Demo Rímac"
    assert rimac.json()["organization_timezone"] == "America/Lima"
    assert rimac.json()["roles"] == ["operator"]
    assert aislamiento.status_code == 200, aislamiento.text
    assert aislamiento.json()["organization_id"] == str(data.AISLAMIENTO.id)
    assert aislamiento.json()["organization_name"] == "Prueba de aislamiento"
    assert aislamiento.json()["roles"] == ["admin"]


@pytest.mark.parametrize(
    ("sub", "organization"),
    [
        pytest.param(SUB_SIN_ORG, None, id="sin-org"),
        pytest.param(SUB_DOS_ORGS, {**RIMAC, **AISLAMIENTO}, id="dos-orgs"),
        pytest.param(SUB_SIN_ORG, {"fantasma": {"id": str(uuid7())}}, id="org-no-registrada"),
        pytest.param(SUB_SIN_ORG, ["rimac"], id="formato-lista"),
    ],
)
async def test_anything_but_one_registered_organization_gets_403(
    client: httpx2.AsyncClient, tokens: TokenFactory, sub: UUID, organization: object
) -> None:
    response = await _me(client, tokens.issue(sub, organization=organization))
    assert response.status_code == 403, response.text


@pytest.mark.parametrize(
    "make_token",
    [
        pytest.param(lambda t: None, id="sin-token"),
        pytest.param(lambda t: "no-es-un-jwt", id="basura"),
        pytest.param(
            lambda t: t.issue(
                SUB_RIMAC_OPERATOR, organization=RIMAC, lifetime=-timedelta(minutes=5)
            ),
            id="expirado",
        ),
        pytest.param(
            lambda t: t.issue(SUB_RIMAC_OPERATOR, organization=RIMAC, aud="otro-cliente"),
            id="otra-audiencia",
        ),
    ],
)
async def test_invalid_or_missing_token_gets_401(
    client: httpx2.AsyncClient,
    tokens: TokenFactory,
    make_token: Callable[[TokenFactory], str | None],
) -> None:
    response = await _me(client, make_token(tokens))
    assert response.status_code == 401, response.text
    assert response.headers["www-authenticate"].startswith("Bearer")


async def test_user_row_is_created_once_and_follows_keycloak(
    client: httpx2.AsyncClient, tokens: TokenFactory, owner: asyncpg.Connection
) -> None:
    sub = uuid7()  # usuario nuevo, para no chocar con otros tests
    first = tokens.issue(sub, organization=RIMAC, email=f"{sub}@rimac.vigia.test", name="Ana")
    renamed = tokens.issue(sub, organization=RIMAC, email=f"{sub}@rimac.vigia.test", name="Ana M.")

    assert (await _me(client, first)).status_code == 200
    assert (await _me(client, first)).status_code == 200
    assert (await _me(client, renamed)).status_code == 200

    rows = await owner.fetch("SELECT organization_id, full_name FROM core.users WHERE id = $1", sub)
    assert [(r["organization_id"], r["full_name"]) for r in rows] == [(data.RIMAC.id, "Ana M.")]


async def test_health_needs_no_token(client: httpx2.AsyncClient) -> None:
    assert (await client.get("/health")).status_code == 200
