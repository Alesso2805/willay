"""Verbatim copy of the SPEC.md table in the "Permissions by role" section.

Tests compare the code's matrix against this copy: changing one without the other
fails CI, so the specification gets reviewed too.
"""

from willay.identity.domain.permissions import Permission
from willay.identity.domain.principal import Role

SPEC_MATRIX: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset({Permission.VIEW}),
    Role.RESPONDER: frozenset({Permission.VIEW, Permission.ACKNOWLEDGE_INCIDENTS}),
    Role.OPERATOR: frozenset(
        {
            Permission.VIEW,
            Permission.ACKNOWLEDGE_INCIDENTS,
            Permission.RESOLVE_INCIDENTS,
            Permission.MANAGE_TERRITORY,
            Permission.MANAGE_RULES,
            Permission.VIEW_CONTACT_DETAILS,
        }
    ),
    Role.ADMIN: frozenset(Permission),
}
