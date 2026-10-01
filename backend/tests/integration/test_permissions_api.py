"""VIG-07: 403 by role, tested for every realm role against every permission.

A probe route per permission is mounted, protected with `require(...)` exactly as the real
endpoints use it.
"""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import httpx2
import pytest
from fastapi import APIRouter, Depends

from tests.integration.api import api_client, bearer
from tests.integration.conftest import Database
from tests.support.matrix import SPEC_MATRIX
from tests.support.tokens import (
    RIMAC,
    SUB_RIMAC_ADMIN,
    SUB_RIMAC_OPERATOR,
    SUB_RIMAC_RESPONDER,
    SUB_RIMAC_VIEWER,
    SUB_TWO_ORGS,
    TokenFactory,
)
from willay.identity.api.dependencies import require
from willay.identity.domain.permissions import Permission
from willay.identity.domain.principal import Principal, Role
from willay.seed import data

pytestmark = pytest.mark.integration

SUB_BY_ROLE: dict[Role, UUID] = {
    Role.ADMIN: SUB_RIMAC_ADMIN,
    Role.OPERATOR: SUB_RIMAC_OPERATOR,
    Role.RESPONDER: SUB_RIMAC_RESPONDER,
    Role.VIEWER: SUB_RIMAC_VIEWER,
}

probe = APIRouter(prefix="/test/permissions")


def _add_probe(permission: Permission) -> None:
    @probe.get(f"/{permission.value}", name=f"probe_{permission.name.lower()}")
    async def endpoint(
        principal: Annotated[Principal, Depends(require(permission))],
    ) -> dict[str, str]:
        return {"organization_id": str(principal.organization_id)}


for _permission in Permission:
    _add_probe(_permission)


@pytest.fixture
async def client(database: Database, tokens: TokenFactory) -> AsyncIterator[httpx2.AsyncClient]:
    async with api_client(database, tokens, probe) as client:
        yield client


@pytest.mark.parametrize(("role", "permission"), [(r, p) for r in Role for p in Permission])
async def test_each_role_gets_exactly_its_permissions(
    client: httpx2.AsyncClient, tokens: TokenFactory, role: Role, permission: Permission
) -> None:
    token = tokens.issue(SUB_BY_ROLE[role], organization=RIMAC, roles=(role.value,))
    response = await client.get(f"/test/permissions/{permission.value}", headers=bearer(token))

    if permission in SPEC_MATRIX[role]:
        assert response.status_code == 200, response.text
        # require() returns the Principal, so the endpoint still has the tenant.
        assert response.json() == {"organization_id": str(data.RIMAC.id)}
    else:
        assert response.status_code == 403, response.text
        assert permission.value in response.json()["detail"]


async def test_user_without_known_roles_can_only_see_who_they_are(
    client: httpx2.AsyncClient, tokens: TokenFactory
) -> None:
    token = tokens.issue(SUB_RIMAC_VIEWER, organization=RIMAC, roles=())

    me = await client.get("/v1/me", headers=bearer(token))
    assert me.status_code == 200
    assert me.json()["roles"] == []
    assert me.json()["permissions"] == []

    view = await client.get(f"/test/permissions/{Permission.VIEW.value}", headers=bearer(token))
    assert view.status_code == 403


async def test_me_lists_the_permissions_of_the_role(
    client: httpx2.AsyncClient, tokens: TokenFactory
) -> None:
    token = tokens.issue(SUB_RIMAC_RESPONDER, organization=RIMAC, roles=("responder",))
    me = await client.get("/v1/me", headers=bearer(token))
    assert set(me.json()["permissions"]) == {p.value for p in SPEC_MATRIX[Role.RESPONDER]}


async def test_tenant_check_comes_before_permissions(
    client: httpx2.AsyncClient, tokens: TokenFactory
) -> None:
    # An admin of two organizations never reaches the permission check: tenant 403.
    token = tokens.issue(
        SUB_TWO_ORGS,
        organization={**RIMAC, "aislamiento": {"id": str(data.ISOLATION.keycloak_org_id)}},
        roles=("admin",),
    )
    response = await client.get(f"/test/permissions/{Permission.VIEW.value}", headers=bearer(token))
    assert response.status_code == 403
    assert "organización" in response.json()["detail"]
