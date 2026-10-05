"""OrganizationRepository over core.organizations (willay_app role)."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from willay.identity.application.organization import Organization
from willay.identity.domain.organization import OrganizationSettings
from willay.shared.languages import Language

_GET = "SELECT id, name, language, timezone FROM core.organizations WHERE id = :id"
_UPDATE = text(
    "UPDATE core.organizations SET language = :language, timezone = :timezone WHERE id = :id"
)


class SqlOrganizationRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get(self, organization_id: UUID, *, for_update: bool = False) -> Organization:
        # Always found: the principal's organization was resolved from this very table.
        query = text(_GET + (" FOR UPDATE" if for_update else ""))
        row = (await self._conn.execute(query, {"id": organization_id})).one()
        return Organization(row.id, row.name, Language(row.language), row.timezone)

    async def update(self, organization_id: UUID, settings: OrganizationSettings) -> None:
        await self._conn.execute(
            _UPDATE,
            {"id": organization_id, "language": settings.language, "timezone": settings.timezone},
        )
