"""The just-in-time user row (VIG-06) when a new user's first requests arrive together."""

import asyncio
from collections.abc import AsyncIterator

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine
from uuid_utils.compat import uuid7

from tests.integration.conftest import Database
from tests.integration.factories import create_organization
from willay.identity.application.authenticate import UserProfile
from willay.identity.infrastructure.repositories import SqlUserRepository
from willay.shared.db import create_engine

pytestmark = pytest.mark.integration

# A dashboard that opens asks for several things at once, each request upserting its user. The
# race is a matter of timing, so it is given many chances.
REQUESTS = 8
ROUNDS = 25


@pytest.fixture
async def engine(database: Database) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


async def _request(engine: AsyncEngine, profile: UserProfile) -> None:
    async with engine.begin() as conn:
        await SqlUserRepository(conn).upsert(profile)
        # The request goes on in the same transaction, which must still be usable.
        await conn.execute(text("SELECT 1"))


async def test_a_new_users_first_requests_arriving_together_all_succeed(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    organization = await create_organization(owner)
    for _ in range(ROUNDS):
        user = uuid7()
        profile = UserProfile(user, organization, f"{user}@x.test", "New user")
        await asyncio.gather(*(_request(engine, profile) for _ in range(REQUESTS)))
        assert await owner.fetchval("SELECT count(*) FROM core.users WHERE id = $1", user) == 1


async def test_an_email_that_belongs_to_another_user_still_fails(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    organization = await create_organization(owner)
    email = f"{uuid7()}@x.test"
    await _request(engine, UserProfile(uuid7(), organization, email, "First"))
    with pytest.raises(IntegrityError):
        await _request(engine, UserProfile(uuid7(), organization, email.upper(), "Second"))
