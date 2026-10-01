from uuid import uuid4

import pytest

from tests.support.matrix import SPEC_MATRIX
from willay.identity.domain.permissions import GRANTS, Permission, can, permissions_of
from willay.identity.domain.principal import Principal, Role


def _principal(*roles: Role) -> Principal:
    return Principal(
        user_id=uuid4(),
        organization_id=uuid4(),
        keycloak_org_id=uuid4(),
        organization_name="Org",
        organization_timezone="America/Lima",
        email="x@willay.test",
        full_name="X",
        roles=frozenset(roles),
    )


@pytest.mark.parametrize("role", list(Role))
def test_each_role_has_exactly_the_permissions_in_spec(role: Role) -> None:
    assert permissions_of([role]) == SPEC_MATRIX[role]


def test_every_permission_is_granted_to_someone() -> None:
    assert set(GRANTS) == set(Permission)
    assert all(GRANTS.values())


def test_no_known_role_means_no_permission() -> None:
    assert permissions_of([]) == frozenset()
    assert not any(can(_principal(), p) for p in Permission)


def test_roles_add_up() -> None:
    assert permissions_of([Role.VIEWER, Role.RESPONDER]) == SPEC_MATRIX[Role.RESPONDER]


@pytest.mark.parametrize(("role", "permission"), [(r, p) for r in Role for p in Permission])
def test_can_matches_the_matrix(role: Role, permission: Permission) -> None:
    assert can(_principal(role), permission) == (permission in SPEC_MATRIX[role])
