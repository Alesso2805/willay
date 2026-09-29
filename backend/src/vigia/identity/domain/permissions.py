"""Matriz de permisos por rol (SPEC.md, sección "Permisos por rol").

Los endpoints declaran un Permission, nunca una lista de roles: si cambia quién puede
hacer algo, cambia esta tabla (y su test), no cada endpoint.
"""

from collections.abc import Iterable, Mapping
from enum import StrEnum
from types import MappingProxyType

from vigia.identity.domain.principal import Principal, Role


class Permission(StrEnum):
    VIEW = "view"
    ACKNOWLEDGE_INCIDENTS = "incidents:acknowledge"  # confirmar y comentar
    RESOLVE_INCIDENTS = "incidents:resolve"  # resuelto o falsa alarma
    MANAGE_TERRITORY = "territory:manage"  # zonas, estaciones, rotación de API keys
    MANAGE_RULES = "rules:manage"
    VIEW_CONTACT_DETAILS = "contacts:view_details"  # email y chat_id (datos personales)
    MANAGE_CONTACTS = "contacts:manage"  # contactos y grupos
    MANAGE_POLICIES = "policies:manage"
    VIEW_AUDIT_LOG = "audit:view"


_EVERYONE = frozenset(Role)
_RESPONDERS = frozenset({Role.RESPONDER, Role.OPERATOR, Role.ADMIN})
_OPERATORS = frozenset({Role.OPERATOR, Role.ADMIN})
_ADMINS = frozenset({Role.ADMIN})

GRANTS: Mapping[Permission, frozenset[Role]] = MappingProxyType(
    {
        Permission.VIEW: _EVERYONE,
        Permission.ACKNOWLEDGE_INCIDENTS: _RESPONDERS,
        Permission.RESOLVE_INCIDENTS: _OPERATORS,
        Permission.MANAGE_TERRITORY: _OPERATORS,
        Permission.MANAGE_RULES: _OPERATORS,
        Permission.VIEW_CONTACT_DETAILS: _OPERATORS,
        Permission.MANAGE_CONTACTS: _ADMINS,
        Permission.MANAGE_POLICIES: _ADMINS,
        Permission.VIEW_AUDIT_LOG: _ADMINS,
    }
)


def permissions_of(roles: Iterable[Role]) -> frozenset[Permission]:
    """Varios roles suman permisos; sin roles conocidos, ningún permiso."""
    held = frozenset(roles)
    return frozenset(p for p, allowed in GRANTS.items() if not allowed.isdisjoint(held))


def can(principal: Principal, permission: Permission) -> bool:
    return not GRANTS[permission].isdisjoint(principal.roles)
