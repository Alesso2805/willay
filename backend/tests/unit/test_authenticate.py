from typing import Any
from uuid import UUID

import pytest

from willay.identity.application.authenticate import (
    InvalidClaimsError,
    Organization,
    UserProfile,
    authenticate,
)
from willay.identity.domain.principal import (
    MultipleOrganizationsError,
    Role,
    UnknownOrganizationError,
)

KC_RIMAC = UUID("1d44f4b3-b1df-457f-b717-20926a20166e")
ORG_RIMAC = UUID("01a0dc43-cd2d-7522-8430-867cee8f89ce")
RIMAC = Organization(ORG_RIMAC, "Demo Rímac", "America/Lima")
SUB = UUID("c144b510-2abd-4844-ad5e-13e700b29fba")


class FakeOrganizations:
    def __init__(self, known: dict[UUID, Organization]) -> None:
        self.known = known

    async def by_keycloak_id(self, keycloak_org_id: UUID) -> Organization | None:
        return self.known.get(keycloak_org_id)


class FakeUsers:
    def __init__(self) -> None:
        self.upserted: list[UserProfile] = []

    async def upsert(self, profile: UserProfile) -> None:
        self.upserted.append(profile)


def _claims(**overrides: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "sub": str(SUB),
        "email": "operador@rimac.willay.test",
        "name": "Óscar Operador Rímac",
        "organization": {"rimac": {"id": str(KC_RIMAC)}},
        "realm_access": {"roles": ["operator", "default-roles-willay"]},
    }
    claims.update(overrides)
    return claims


async def test_resolves_tenant_roles_and_upserts_user() -> None:
    users = FakeUsers()
    principal = await authenticate(_claims(), FakeOrganizations({KC_RIMAC: RIMAC}), users)

    assert principal.organization_id == ORG_RIMAC
    assert (principal.organization_name, principal.organization_timezone) == (
        "Demo Rímac",
        "America/Lima",
    )
    assert principal.user_id == SUB
    assert principal.roles == {Role.OPERATOR}
    assert users.upserted == [
        UserProfile(SUB, ORG_RIMAC, "operador@rimac.willay.test", "Óscar Operador Rímac")
    ]


async def test_organization_unknown_to_willay_is_rejected_without_creating_user() -> None:
    users = FakeUsers()
    with pytest.raises(UnknownOrganizationError):
        await authenticate(_claims(), FakeOrganizations({}), users)
    assert users.upserted == []


async def test_multiple_organizations_are_rejected_before_any_lookup() -> None:
    claim = {"rimac": {"id": str(KC_RIMAC)}, "other": {"id": str(ORG_RIMAC)}}
    with pytest.raises(MultipleOrganizationsError):
        await authenticate(_claims(organization=claim), FakeOrganizations({}), FakeUsers())


@pytest.mark.parametrize("missing", ["sub", "email"])
async def test_missing_identity_claims_are_invalid(missing: str) -> None:
    claims = _claims()
    del claims[missing]
    with pytest.raises(InvalidClaimsError):
        await authenticate(claims, FakeOrganizations({KC_RIMAC: RIMAC}), FakeUsers())


async def test_missing_realm_roles_means_no_roles() -> None:
    principal = await authenticate(
        _claims(realm_access=None), FakeOrganizations({KC_RIMAC: RIMAC}), FakeUsers()
    )
    assert principal.roles == frozenset()
