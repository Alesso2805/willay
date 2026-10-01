"""Quién hace la petición y en nombre de qué organización (ADR-0004).

Reglas:
- El claim `organization` es un objeto `{alias: {"id": uuid}}`. Se exige exactamente
  una clave; cero, varias o un formato distinto se rechazan (fail closed).
- El tenant se identifica por el `id` de Keycloak, nunca por el alias.
- Los roles son los realm roles de Keycloak que Vigía conoce; el resto se ignora.
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
    """El token es auténtico pero no identifica exactamente una organización válida (403)."""


class NoOrganizationError(TenantError):
    pass


class MultipleOrganizationsError(TenantError):
    pass


class MalformedOrganizationClaimError(TenantError):
    pass


class UnknownOrganizationError(TenantError):
    """La organización existe en Keycloak pero no en core.organizations."""


@dataclass(frozen=True)
class OrganizationMembership:
    alias: str
    keycloak_org_id: UUID


@dataclass(frozen=True)
class Principal:
    user_id: UUID  # = sub de Keycloak = core.users.id
    organization_id: UUID  # core.organizations.id: el tenant de todas las consultas
    keycloak_org_id: UUID
    organization_name: str
    organization_timezone: str  # IANA, p. ej. America/Lima
    email: str
    full_name: str
    roles: frozenset[Role]

    def has_any(self, *roles: Role) -> bool:
        return not self.roles.isdisjoint(roles)


def single_organization(claim: object) -> OrganizationMembership:
    if claim is None:
        raise NoOrganizationError("el token no trae el claim organization")
    # Una lista es el formato sin "Add organization id": solo alias, sin id. Se rechaza.
    if not isinstance(claim, Mapping):
        raise MalformedOrganizationClaimError("organization debe ser un objeto {alias: {id}}")
    if len(claim) == 0:
        raise NoOrganizationError("el usuario no pertenece a ninguna organización")
    if len(claim) > 1:
        raise MultipleOrganizationsError("el usuario pertenece a varias organizaciones")

    ((alias, value),) = claim.items()
    raw_id = value.get("id") if isinstance(value, Mapping) else None
    if not isinstance(alias, str) or not isinstance(raw_id, str):
        raise MalformedOrganizationClaimError("falta el id de la organización en el claim")
    try:
        return OrganizationMembership(alias, UUID(raw_id))
    except ValueError as exc:
        raise MalformedOrganizationClaimError("el id de la organización no es un uuid") from exc


def known_roles(realm_roles: Iterable[object]) -> frozenset[Role]:
    # Keycloak añade roles propios (default-roles-vigia, offline_access...): se ignoran.
    valid = {role.value for role in Role}
    return frozenset(Role(r) for r in realm_roles if isinstance(r, str) and r in valid)
