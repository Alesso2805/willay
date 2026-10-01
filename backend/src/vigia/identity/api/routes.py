from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from vigia.identity.api.dependencies import CurrentPrincipal
from vigia.identity.domain.permissions import Permission, permissions_of
from vigia.identity.domain.principal import Role

router = APIRouter(prefix="/v1", tags=["identity"])


class MeResponse(BaseModel):
    user_id: UUID
    email: str
    full_name: str
    organization_id: UUID
    keycloak_org_id: UUID
    organization_name: str
    organization_timezone: str = Field(
        description="Zona horaria IANA de la organización: el panel muestra las horas en ella."
    )
    roles: list[Role]
    permissions: list[Permission] = Field(
        description="Para que el panel oculte acciones; la API las valida igual en cada endpoint."
    )


@router.get("/me", summary="Usuario autenticado, su organización, roles y permisos")
async def me(principal: CurrentPrincipal) -> MeResponse:
    return MeResponse(
        user_id=principal.user_id,
        email=principal.email,
        full_name=principal.full_name,
        organization_id=principal.organization_id,
        keycloak_org_id=principal.keycloak_org_id,
        organization_name=principal.organization_name,
        organization_timezone=principal.organization_timezone,
        roles=sorted(principal.roles),
        permissions=sorted(permissions_of(principal.roles)),
    )
