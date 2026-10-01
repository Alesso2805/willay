"""Use case: from verified claims to a Principal with a resolved tenant."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from vigia.identity.domain.principal import (
    Principal,
    UnknownOrganizationError,
    known_roles,
    single_organization,
)


@dataclass(frozen=True)
class UserProfile:
    user_id: UUID
    organization_id: UUID
    email: str
    full_name: str


@dataclass(frozen=True)
class Organization:
    id: UUID
    name: str
    timezone: str  # IANA: the dashboard and messages show times in this zone


class OrganizationRepository(Protocol):
    async def by_keycloak_id(self, keycloak_org_id: UUID) -> Organization | None: ...


class UserRepository(Protocol):
    async def upsert(self, profile: UserProfile) -> None: ...


class InvalidClaimsError(Exception):
    """Required claims (sub, email) are missing: the token is unusable for Willay (401)."""


async def authenticate(
    claims: Mapping[str, Any],
    organizations: OrganizationRepository,
    users: UserRepository,
) -> Principal:
    membership = single_organization(claims.get("organization"))
    organization = await organizations.by_keycloak_id(membership.keycloak_org_id)
    if organization is None:
        raise UnknownOrganizationError(
            f"organization {membership.keycloak_org_id} is not registered in Willay"
        )
    organization_id = organization.id

    try:
        user_id = UUID(str(claims["sub"]))
        email = str(claims["email"])
    except (KeyError, ValueError) as exc:
        raise InvalidClaimsError("the token must carry sub (uuid) and email") from exc
    full_name = str(claims.get("name") or email)

    # Just-in-time upsert: Keycloak is the source of truth; the row exists for the FKs
    # (rules.created_by, incidents.acknowledged_by_user_id).
    await users.upsert(UserProfile(user_id, organization_id, email, full_name))

    realm_access = claims.get("realm_access")
    raw_roles = realm_access.get("roles", []) if isinstance(realm_access, Mapping) else []
    return Principal(
        user_id=user_id,
        organization_id=organization_id,
        keycloak_org_id=membership.keycloak_org_id,
        organization_name=organization.name,
        organization_timezone=organization.timezone,
        email=email,
        full_name=full_name,
        roles=known_roles(raw_roles),
    )
