"""Repositorios SQL de identidad (rol vigia_app)."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from vigia.identity.application.authenticate import UserProfile


class SqlOrganizationRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def id_by_keycloak_id(self, keycloak_org_id: UUID) -> UUID | None:
        result = await self._conn.scalar(
            text("SELECT id FROM core.organizations WHERE keycloak_org_id = :kc_id"),
            {"kc_id": keycloak_org_id},
        )
        return result if isinstance(result, UUID) else None


class SqlUserRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def upsert(self, profile: UserProfile) -> None:
        # El WHERE convierte el upsert en no-op cuando nada cambió: sin escritura ni WAL
        # en cada petición autenticada, solo cuando Keycloak cambia nombre, email u org.
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
