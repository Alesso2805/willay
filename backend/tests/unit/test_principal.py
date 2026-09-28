from uuid import UUID

import pytest

from vigia.identity.domain.principal import (
    MalformedOrganizationClaimError,
    MultipleOrganizationsError,
    NoOrganizationError,
    OrganizationMembership,
    Role,
    TenantError,
    known_roles,
    single_organization,
)

RIMAC_ID = "1d44f4b3-b1df-457f-b717-20926a20166e"
AISLAMIENTO_ID = "d32ffb77-666e-4986-8234-9f1db8437302"


def test_single_organization_is_resolved_by_id() -> None:
    membership = single_organization({"rimac": {"id": RIMAC_ID}})
    assert membership == OrganizationMembership("rimac", UUID(RIMAC_ID))


@pytest.mark.parametrize(
    ("claim", "error"),
    [
        (None, NoOrganizationError),
        ({}, NoOrganizationError),
        (
            {"rimac": {"id": RIMAC_ID}, "aislamiento": {"id": AISLAMIENTO_ID}},
            MultipleOrganizationsError,
        ),
        # Formato sin "Add organization id": solo alias. No sirve para resolver el tenant.
        (["rimac"], MalformedOrganizationClaimError),
        # Lo que emiten dos mappers a la vez (visto en VIG-02): también se rechaza.
        (["rimac", {"rimac": {"id": RIMAC_ID}}], MalformedOrganizationClaimError),
        ({"rimac": {}}, MalformedOrganizationClaimError),
        ({"rimac": {"id": 42}}, MalformedOrganizationClaimError),
        ({"rimac": {"id": "no-es-uuid"}}, MalformedOrganizationClaimError),
        ({"rimac": "1d44f4b3"}, MalformedOrganizationClaimError),
        ("rimac", MalformedOrganizationClaimError),
    ],
)
def test_anything_but_exactly_one_organization_is_rejected(
    claim: object, error: type[TenantError]
) -> None:
    with pytest.raises(error):
        single_organization(claim)


def test_all_tenant_errors_share_a_base_class() -> None:
    # La API traduce TenantError a 403 sin distinguir la causa.
    for error in (NoOrganizationError, MultipleOrganizationsError, MalformedOrganizationClaimError):
        assert issubclass(error, TenantError)


def test_known_roles_ignores_keycloak_internal_roles() -> None:
    roles = known_roles(["operator", "default-roles-vigia", "offline_access", 7, "viewer"])
    assert roles == {Role.OPERATOR, Role.VIEWER}
