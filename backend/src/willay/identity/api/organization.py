"""The organization's settings: every role reads them, an admin changes them."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from willay.identity.api.dependencies import require
from willay.identity.application.organization import Organization, update_organization
from willay.identity.domain.organization import InvalidOrganizationError, OrganizationSettings
from willay.identity.domain.permissions import Permission
from willay.identity.domain.principal import Principal
from willay.identity.infrastructure.organizations_repository import SqlOrganizationRepository
from willay.shared.audit import SqlAuditLog
from willay.shared.languages import Language
from willay.shared.web import ClockDep, DbConnection, invalid_field

router = APIRouter(prefix="/v1/organization", tags=["identity"])

CanView = Annotated[Principal, Depends(require(Permission.VIEW))]
CanManage = Annotated[Principal, Depends(require(Permission.MANAGE_ORGANIZATION))]


class OrganizationOut(BaseModel):
    id: UUID
    name: str
    language: Language = Field(
        description="The language of the alerts of its contacts that chose none."
    )
    timezone: str = Field(description="IANA name: every time Willay writes for it uses it.")


class OrganizationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language
    timezone: str = Field(min_length=1, max_length=64, examples=["America/Lima"])


@router.get("", summary="The user's organization: its language and time zone")
async def get_organization(principal: CanView, conn: DbConnection) -> OrganizationOut:
    return _out(await SqlOrganizationRepository(conn).get(principal.organization_id))


@router.put(
    "",
    summary="Change the organization's language and time zone (audited)",
    responses={422: {"description": "The time zone is not an IANA name"}},
)
async def put_organization(
    body: OrganizationIn, principal: CanManage, conn: DbConnection, clock: ClockDep
) -> OrganizationOut:
    try:
        organization = await update_organization(
            principal.organization_id,
            principal.user_id,
            OrganizationSettings(body.language, body.timezone),
            organizations=SqlOrganizationRepository(conn),
            audit=SqlAuditLog(conn),
            clock=clock,
        )
    except InvalidOrganizationError as exc:
        raise invalid_field(exc) from exc
    return _out(organization)


def _out(organization: Organization) -> OrganizationOut:
    return OrganizationOut(
        id=organization.id,
        name=organization.name,
        language=organization.language,
        timezone=organization.timezone,
    )
