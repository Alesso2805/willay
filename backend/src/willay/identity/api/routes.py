from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from willay.identity.api.dependencies import CurrentPrincipal
from willay.identity.domain.permissions import Permission, permissions_of
from willay.identity.domain.principal import Role

router = APIRouter(prefix="/v1", tags=["identity"])


class MeResponse(BaseModel):
    user_id: UUID
    email: str
    full_name: str
    organization_id: UUID
    keycloak_org_id: UUID
    organization_name: str
    organization_timezone: str = Field(
        description="The organization's IANA time zone: the dashboard shows times in it."
    )
    roles: list[Role]
    permissions: list[Permission] = Field(
        description="So the dashboard can hide actions; the API checks them on every endpoint."
    )


@router.get("/me", summary="The authenticated user, their organization, roles and permissions")
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
