from uuid import UUID

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from willay.identity.api.dependencies import CurrentPrincipal
from willay.identity.domain.permissions import Permission, permissions_of
from willay.identity.domain.principal import Role
from willay.identity.infrastructure.repositories import SqlUserRepository
from willay.shared.languages import Language
from willay.shared.web import DbConnection

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
    language: Language | None = Field(
        description="The dashboard language the user chose; null until they choose one, and"
        " meanwhile the dashboard follows the browser's."
    )


class LanguageIn(BaseModel):
    language: Language


@router.get("/me", summary="The authenticated user, their organization, roles and permissions")
async def me(principal: CurrentPrincipal, conn: DbConnection) -> MeResponse:
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
        language=await SqlUserRepository(conn).language(principal.user_id),
    )


# Any signed-in user, roles or not: like /v1/me, it is about the user, not the organization.
@router.put(
    "/me/language",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Save the dashboard language the user chose",
)
async def choose_language(
    body: LanguageIn, principal: CurrentPrincipal, conn: DbConnection
) -> Response:
    await SqlUserRepository(conn).set_language(principal.user_id, body.language)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
