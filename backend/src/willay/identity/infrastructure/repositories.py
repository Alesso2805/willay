"""Identity SQL repositories (willay_app role)."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from willay.identity.application.authenticate import Organization, UserProfile


class SqlOrganizationRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def by_keycloak_id(self, keycloak_org_id: UUID) -> Organization | None:
        row = (
            await self._conn.execute(
                text(
                    "SELECT id, name, timezone FROM core.organizations"
                    " WHERE keycloak_org_id = :kc_id"
                ),
                {"kc_id": keycloak_org_id},
            )
        ).first()
        return Organization(row.id, row.name, row.timezone) if row is not None else None


class SqlUserRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def upsert(self, profile: UserProfile) -> None:
        # The WHERE makes the upsert a no-op when nothing changed: no write or WAL on every
        # authenticated request, only when Keycloak changes the name, email or org.
        await self._conn.execute(
            text("""
                INSERT INTO core.users (id, organization_id, email, full_name)
                VALUES (:id, :organization_id, :email, :full_name)
                ON CONFLICT (id) DO UPDATE
                SET organization_id = EXCLUDED.organization_id,
                    email = EXCLUDED.email,
                    full_name = EXCLUDED.full_name
                WHERE (core.users.organization_id, core.users.email, core.users.full_name)
                      IS DISTINCT FROM
                      (EXCLUDED.organization_id, EXCLUDED.email, EXCLUDED.full_name)
            """),
            {
                "id": profile.user_id,
                "organization_id": profile.organization_id,
                "email": profile.email,
                "full_name": profile.full_name,
            },
        )
