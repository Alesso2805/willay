"""VIG-40: API errors carry a stable code and a message in the request's Accept-Language."""

from collections.abc import AsyncIterator
from uuid import uuid4

import httpx2
import pytest

from tests.integration.api import api_client, bearer
from tests.integration.conftest import Database
from tests.support.tokens import RIMAC, SUB_RIMAC_OPERATOR, SUB_RIMAC_VIEWER, TokenFactory

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(database: Database, tokens: TokenFactory) -> AsyncIterator[httpx2.AsyncClient]:
    async with api_client(database, tokens) as client:
        yield client


def _headers(token: str, language: str | None = None) -> dict[str, str]:
    headers = bearer(token)
    if language is not None:
        headers["Accept-Language"] = language
    return headers


async def test_an_error_answers_in_the_requested_language_with_the_same_code(
    client: httpx2.AsyncClient, tokens: TokenFactory
) -> None:
    token = tokens.issue(SUB_RIMAC_OPERATOR, organization=RIMAC)
    url = f"/v1/incidents/{uuid4()}"

    english = await client.get(url, headers=_headers(token, "en-US,en;q=0.9"))
    spanish = await client.get(url, headers=_headers(token, "es-PE"))
    default = await client.get(url, headers=_headers(token))

    assert english.status_code == spanish.status_code == default.status_code == 404
    assert english.json() == {"detail": "Incident not found", "code": "incident_not_found"}
    assert english.headers["content-language"] == "en"
    assert spanish.json() == {"detail": "Incidente no encontrado", "code": "incident_not_found"}
    assert default.json() == spanish.json()  # Spanish when the client does not say


async def test_permission_and_authentication_errors_are_translated_too(
    client: httpx2.AsyncClient, tokens: TokenFactory
) -> None:
    viewer = tokens.issue(SUB_RIMAC_VIEWER, organization=RIMAC, roles=("viewer",))
    forbidden = await client.post(
        "/v1/rules/preview", headers=_headers(viewer, "en"), json={"type": "silence"}
    )
    assert forbidden.status_code == 403
    assert forbidden.json() == {
        "detail": "Your role does not have the permission rules:manage",
        "code": "permission_denied",
    }

    anonymous = await client.get("/v1/me", headers={"Accept-Language": "en"})
    assert anonymous.status_code == 401
    assert anonymous.json()["code"] == "token_invalid"
    assert anonymous.headers["www-authenticate"] == 'Bearer error="invalid_token"'

    keyless = await client.post("/v1/readings", headers={"Accept-Language": "en"}, json={})
    assert keyless.status_code == 401
    assert keyless.json() == {"detail": "Missing or invalid API key", "code": "api_key_invalid"}


async def test_an_invalid_field_keeps_fastapis_shape_with_its_code(
    client: httpx2.AsyncClient, tokens: TokenFactory
) -> None:
    admin = tokens.issue(SUB_RIMAC_OPERATOR, organization=RIMAC, roles=("admin",))
    response = await client.get(
        "/v1/audit",
        headers=_headers(admin, "en"),
        params={"since": "2026-10-04T00:00:00Z", "until": "2026-10-03T00:00:00Z"},
    )
    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "loc": ["query", "since"],
                "msg": "The start date must be before the end date.",
                "type": "value_error",
                "code": "audit_date_order",
            }
        ],
        "code": "audit_date_order",
    }


async def test_a_domain_validation_error_is_translated_with_its_parameters(
    client: httpx2.AsyncClient, tokens: TokenFactory
) -> None:
    admin = tokens.issue(SUB_RIMAC_OPERATOR, organization=RIMAC, roles=("admin",))
    body = {"full_name": "x" * 500, "email": None}

    english = await client.post("/v1/contacts", headers=_headers(admin, "en"), json=body)
    spanish = await client.post("/v1/contacts", headers=_headers(admin, "es"), json=body)

    assert english.status_code == spanish.status_code == 422
    [problem] = english.json()["detail"]
    assert problem["loc"] == ["body", "full_name"]
    assert problem["code"] == "contact_name_length"
    assert problem["msg"].startswith("The name must have between 1 and ")
    assert spanish.json()["detail"][0]["msg"].startswith("El nombre debe tener entre 1 y ")
