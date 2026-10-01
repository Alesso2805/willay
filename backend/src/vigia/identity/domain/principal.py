"""Who makes the request and on behalf of which organization (ADR-0004).

- The `organization` claim is an object `{alias: {"id": uuid}}` with exactly one key; zero,
  several or any other shape is rejected (fail closed).
- The tenant is identified by the Keycloak `id`, never by the alias.
- Roles are the Keycloak realm roles Vigía knows; the rest are ignored.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class Role(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    RESPONDER = "responder"
    VIEWER = "viewer"


class TenantError(Exception):
    """The token is authentic but does not identify exactly one valid organization (403)."""


class NoOrganizationError(TenantError):
    pass


class MultipleOrganizationsError(TenantError):
    pass


class MalformedOrganizationClaimError(TenantError):
    pass


class UnknownOrganizationError(TenantError):
    """The organization exists in Keycloak but not in core.organizations."""


@dataclass(frozen=True)
class OrganizationMembership:
    alias: str
    keycloak_org_id: UUID


@dataclass(frozen=True)
class Principal:
    user_id: UUID  # = Keycloak sub = core.users.id
    organization_id: UUID  # core.organizations.id: the tenant for every query
    keycloak_org_id: UUID
    organization_name: str
    organization_timezone: str  # IANA, e.g. America/Lima
    email: str
    full_name: str
    roles: frozenset[Role]

    def has_any(self, *roles: Role) -> bool:
        return not self.roles.isdisjoint(roles)


def single_organization(claim: object) -> OrganizationMembership:
    if claim is None:
        raise NoOrganizationError("the token has no organization claim")
    # A list is the format without "Add organization id" (aliases only, no id): rejected.
    if not isinstance(claim, Mapping):
        raise MalformedOrganizationClaimError("organization must be an object {alias: {id}}")
    if len(claim) == 0:
        raise NoOrganizationError("the user belongs to no organization")
    if len(claim) > 1:
        raise MultipleOrganizationsError("the user belongs to several organizations")

    ((alias, value),) = claim.items()
    raw_id = value.get("id") if isinstance(value, Mapping) else None
    if not isinstance(alias, str) or not isinstance(raw_id, str):
        raise MalformedOrganizationClaimError("the claim is missing the organization id")
    try:
        return OrganizationMembership(alias, UUID(raw_id))
    except ValueError as exc:
        raise MalformedOrganizationClaimError("the organization id is not a uuid") from exc


def known_roles(realm_roles: Iterable[object]) -> frozenset[Role]:
    # Keycloak adds its own roles (default-roles-vigia, offline_access...): ignored.
    valid = {role.value for role in Role}
    return frozenset(Role(r) for r in realm_roles if isinstance(r, str) and r in valid)
