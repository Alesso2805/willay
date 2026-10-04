"""VIG-06: authentication, tenant resolution and 401/403 against the real app and Postgres."""

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
    ISOLATION,
    RIMAC,
    SUB_ISOLATION_ADMIN,
    SUB_NO_ORG,
    SUB_RIMAC_OPERATOR,
    SUB_TWO_ORGS,
    TokenFactory,
)
from willay.seed import data

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
        client, tokens.issue(SUB_ISOLATION_ADMIN, organization=ISOLATION, roles=("admin",))
    )

    assert rimac.status_code == 200, rimac.text
    assert rimac.json()["organization_id"] == str(data.RIMAC.id)
    assert rimac.json()["organization_name"] == "Demo Rímac"
    assert rimac.json()["organization_timezone"] == "America/Lima"
    assert rimac.json()["roles"] == ["operator"]
    assert aislamiento.status_code == 200, aislamiento.text
    assert aislamiento.json()["organization_id"] == str(data.ISOLATION.id)
    assert aislamiento.json()["organization_name"] == "Prueba de aislamiento"
    assert aislamiento.json()["roles"] == ["admin"]


@pytest.mark.parametrize(
    ("sub", "organization"),
    [
        pytest.param(SUB_NO_ORG, None, id="no-org"),
        pytest.param(SUB_TWO_ORGS, {**RIMAC, **ISOLATION}, id="two-orgs"),
        pytest.param(SUB_NO_ORG, {"fantasma": {"id": str(uuid7())}}, id="unregistered-org"),
        pytest.param(SUB_NO_ORG, ["rimac"], id="list-format"),
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
        pytest.param(lambda t: None, id="no-token"),
        pytest.param(lambda t: "no-es-un-jwt", id="garbage"),
        pytest.param(
            lambda t: t.issue(
                SUB_RIMAC_OPERATOR, organization=RIMAC, lifetime=-timedelta(minutes=5)
            ),
            id="expired",
        ),
        pytest.param(
            lambda t: t.issue(SUB_RIMAC_OPERATOR, organization=RIMAC, aud="otro-cliente"),
            id="other-audience",
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
    sub = uuid7()  # a new user, so it does not clash with other tests
    first = tokens.issue(sub, organization=RIMAC, email=f"{sub}@rimac.willay.test", name="Ana")
    renamed = tokens.issue(sub, organization=RIMAC, email=f"{sub}@rimac.willay.test", name="Ana M.")

    assert (await _me(client, first)).status_code == 200
    assert (await _me(client, first)).status_code == 200
    assert (await _me(client, renamed)).status_code == 200

    rows = await owner.fetch("SELECT organization_id, full_name FROM core.users WHERE id = $1", sub)
    assert [(r["organization_id"], r["full_name"]) for r in rows] == [(data.RIMAC.id, "Ana M.")]


async def test_health_needs_no_token(client: httpx2.AsyncClient) -> None:
    assert (await client.get("/health")).status_code == 200


async def test_the_language_is_unset_until_the_user_chooses_one(
    client: httpx2.AsyncClient, tokens: TokenFactory, owner: asyncpg.Connection
) -> None:
    sub = UUID(str(uuid7()))  # a user of their own: other tests do not change their choice
    token = tokens.issue(sub, organization=RIMAC, roles=())
    assert (await _me(client, token)).json()["language"] is None

    chosen = await client.put("/v1/me/language", headers=bearer(token), json={"language": "en"})

    assert chosen.status_code == 204, chosen.text
    assert (await _me(client, token)).json()["language"] == "en"
    assert await owner.fetchval("SELECT language FROM core.users WHERE id = $1", sub) == "en"
    # Keycloak renames the user: the profile is updated and the choice stays.
    renamed = tokens.issue(sub, organization=RIMAC, roles=(), name="Nombre nuevo")
    me = (await _me(client, renamed)).json()
    assert (me["full_name"], me["language"]) == ("Nombre nuevo", "en")


async def test_only_offered_languages_can_be_chosen(
    client: httpx2.AsyncClient, tokens: TokenFactory
) -> None:
    token = tokens.issue(UUID(str(uuid7())), organization=RIMAC)
    response = await client.put("/v1/me/language", headers=bearer(token), json={"language": "fr"})
    assert response.status_code == 422


async def test_choosing_a_language_needs_a_valid_token(client: httpx2.AsyncClient) -> None:
    response = await client.put("/v1/me/language", json={"language": "en"})
    assert response.status_code == 401
