"""Copia literal de la tabla SPEC.md, sección "Permisos por rol".

Los tests comparan la matriz del código contra esta copia: si alguien cambia una sin la
otra, falla CI y se revisa también la especificación.
"""

from vigia.identity.domain.permissions import Permission
from vigia.identity.domain.principal import Role

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
