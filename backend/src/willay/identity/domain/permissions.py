"""Role-to-permission matrix (SPEC.md, "Permissions by role").

Endpoints declare a Permission, never a list of roles: changing who can do something changes
this table (and its test), not every endpoint.
"""

from collections.abc import Iterable, Mapping
from enum import StrEnum
from types import MappingProxyType

from willay.identity.domain.principal import Principal, Role


class Permission(StrEnum):
    VIEW = "view"
    ACKNOWLEDGE_INCIDENTS = "incidents:acknowledge"  # acknowledge and comment
    RESOLVE_INCIDENTS = "incidents:resolve"  # resolved or false alarm
    MANAGE_TERRITORY = "territory:manage"  # zones, stations, API key rotation
    MANAGE_RULES = "rules:manage"
    REPROCESS_READINGS = "readings:reprocess"  # see and reprocess readings that failed evaluation
    VIEW_CONTACT_DETAILS = "contacts:view_details"  # email, Telegram linked or not; never chat_id
    MANAGE_CONTACTS = "contacts:manage"  # contacts and groups
    MANAGE_POLICIES = "policies:manage"
    VIEW_AUDIT_LOG = "audit:view"
    MANAGE_ORGANIZATION = "organization:manage"  # its language and time zone
    RUN_DEMO = "demo:run"  # the public demo's Rímac scenario


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
        Permission.REPROCESS_READINGS: _OPERATORS,
        Permission.VIEW_CONTACT_DETAILS: _OPERATORS,
        Permission.MANAGE_CONTACTS: _ADMINS,
        Permission.MANAGE_POLICIES: _ADMINS,
        Permission.VIEW_AUDIT_LOG: _ADMINS,
        Permission.MANAGE_ORGANIZATION: _ADMINS,
        Permission.RUN_DEMO: _ADMINS,
    }
)


def permissions_of(roles: Iterable[Role]) -> frozenset[Permission]:
    """Several roles add up; no known role means no permission."""
    held = frozenset(roles)
    return frozenset(p for p, allowed in GRANTS.items() if not allowed.isdisjoint(held))


def can(principal: Principal, permission: Permission) -> bool:
    return not GRANTS[permission].isdisjoint(principal.roles)
