"""Caso de uso: de claims verificados a un Principal con tenant resuelto."""

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


class OrganizationRepository(Protocol):
    async def id_by_keycloak_id(self, keycloak_org_id: UUID) -> UUID | None: ...


class UserRepository(Protocol):
    async def upsert(self, profile: UserProfile) -> None: ...


class InvalidClaimsError(Exception):
    """Faltan claims obligatorios (sub, email): el token no sirve para Vigía (401)."""


async def authenticate(
    claims: Mapping[str, Any],
    organizations: OrganizationRepository,
    users: UserRepository,
) -> Principal:
    membership = single_organization(claims.get("organization"))
    organization_id = await organizations.id_by_keycloak_id(membership.keycloak_org_id)
    if organization_id is None:
        raise UnknownOrganizationError(
            f"organización {membership.keycloak_org_id} sin alta en Vigía"
        )

    try:
        user_id = UUID(str(claims["sub"]))
        email = str(claims["email"])
    except (KeyError, ValueError) as exc:
        raise InvalidClaimsError("el token debe traer sub (uuid) y email") from exc
    full_name = str(claims.get("name") or email)

    # Alta o actualización just-in-time: Keycloak es la fuente; la fila existe para las FK
    # (rules.created_by, incidents.acknowledged_by_user_id).
    await users.upsert(UserProfile(user_id, organization_id, email, full_name))

    realm_access = claims.get("realm_access")
    raw_roles = realm_access.get("roles", []) if isinstance(realm_access, Mapping) else []
    return Principal(
        user_id=user_id,
        organization_id=organization_id,
        keycloak_org_id=membership.keycloak_org_id,
        email=email,
        full_name=full_name,
        roles=known_roles(raw_roles),
    )
