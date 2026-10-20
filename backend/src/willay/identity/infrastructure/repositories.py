"""Identity SQL repositories (willay_app role)."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from willay.identity.application.authenticate import Organization, UserProfile
from willay.shared.languages import Language

# The WHERE makes the upsert a no-op when nothing changed: no write or WAL on every
# authenticated request, only when Keycloak changes the name, email or org.
_UPSERT_USER = text("""
    INSERT INTO core.users (id, organization_id, email, full_name)
    VALUES (:id, :organization_id, :email, :full_name)
    ON CONFLICT (id) DO UPDATE
    SET organization_id = EXCLUDED.organization_id,
        email = EXCLUDED.email,
        full_name = EXCLUDED.full_name
    WHERE (core.users.organization_id, core.users.email, core.users.full_name)
          IS DISTINCT FROM
          (EXCLUDED.organization_id, EXCLUDED.email, EXCLUDED.full_name)
""")


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
        params = {
            "id": profile.user_id,
            "organization_id": profile.organization_id,
            "email": profile.email,
            "full_name": profile.full_name,
        }
        # A new user's first requests often arrive together (a dashboard opening). Two inserts
        # of the same row can both pass ON CONFLICT (id)'s check, and the second then trips over
        # the email's unique index, which ON CONFLICT does not cover. In a savepoint, so that
        # leaves the request's transaction usable; the retry finds the committed row and takes
        # the ON CONFLICT path. An email that belongs to another user fails the retry too.
        try:
            async with self._conn.begin_nested():
                await self._conn.execute(_UPSERT_USER, params)
        except IntegrityError:
            async with self._conn.begin_nested():
                await self._conn.execute(_UPSERT_USER, params)

    async def language(self, user_id: UUID) -> Language | None:
        value = await self._conn.scalar(
            text("SELECT language FROM core.users WHERE id = :id"), {"id": user_id}
        )
        return Language(value) if value is not None else None

    async def set_language(self, user_id: UUID, language: Language) -> None:
        await self._conn.execute(
            text("UPDATE core.users SET language = :language WHERE id = :id"),
            {"id": user_id, "language": language.value},
        )
