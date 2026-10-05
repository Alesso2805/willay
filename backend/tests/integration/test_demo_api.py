"""VIG-43: the public demo's API against the real app and Postgres: off by default, only for
the demo organization, only admins start the scenario, and one run at a time."""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import UUID

import asyncpg
import pytest

from tests.integration.api import api_client, bearer
from tests.integration.conftest import Database
from tests.support.tokens import (
    ISOLATION,
    RIMAC,
    SUB_ISOLATION_ADMIN,
    SUB_RIMAC_ADMIN,
    SUB_RIMAC_VIEWER,
    TokenFactory,
)
from willay.seed import data

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def no_runs(owner: asyncpg.Connection) -> AsyncIterator[None]:
    await owner.execute("DELETE FROM core.demo_runs")
    yield
    await owner.execute("DELETE FROM core.demo_runs")


def _as(tokens: TokenFactory, sub: UUID, role: str, organization: Any = RIMAC) -> dict[str, str]:
    return bearer(tokens.issue(sub, organization=organization, roles=(role,)))


async def test_the_demo_is_off_unless_the_server_turns_it_on(
    database: Database, tokens: TokenFactory
) -> None:
    async with api_client(database, tokens) as client:
        admin = _as(tokens, SUB_RIMAC_ADMIN, "admin")
        demo = (await client.get("/v1/demo", headers=admin)).json()
        started = await client.post("/v1/demo/scenario", headers=admin)

    assert (demo["available"], demo["can_run"], demo["run"]) == (False, False, None)
    assert (started.status_code, started.json()["code"]) == (404, "demo_unavailable")


async def test_an_admin_of_the_demo_organization_starts_the_scenario_once(
    database: Database, tokens: TokenFactory
) -> None:
    admin, viewer = _as(tokens, SUB_RIMAC_ADMIN, "admin"), _as(tokens, SUB_RIMAC_VIEWER, "viewer")
    async with api_client(database, tokens, demo_mode=True) as client:
        seen_by_viewer = (await client.get("/v1/demo", headers=viewer)).json()
        by_viewer = await client.post("/v1/demo/scenario", headers=viewer)
        first = await client.post("/v1/demo/scenario", headers=admin)
        second = await client.post("/v1/demo/scenario", headers=admin)
        demo = (await client.get("/v1/demo", headers=admin)).json()

    assert (seen_by_viewer["available"], seen_by_viewer["can_run"]) == (True, False)
    assert by_viewer.status_code == 403
    assert first.status_code == 202
    assert (first.json()["kind"], first.json()["status"]) == ("scenario", "queued")
    assert (second.status_code, second.json()["code"]) == (409, "demo_run_active")
    assert (demo["available"], demo["can_run"]) == (True, True)
    assert demo["run"]["id"] == first.json()["id"]
    assert [step["phase"] for step in demo["timeline"]] == ["normal", "drop", "silence", "done"]
    assert demo["duration_s"] == 540


async def test_another_organization_never_sees_the_demo(
    database: Database, tokens: TokenFactory
) -> None:
    other = _as(tokens, SUB_ISOLATION_ADMIN, "admin", ISOLATION)
    async with api_client(database, tokens, demo_mode=True) as client:
        demo = (await client.get("/v1/demo", headers=other)).json()
        started = await client.post("/v1/demo/scenario", headers=other)

    assert (demo["available"], demo["run"]) == (False, None)
    assert (started.status_code, started.json()["code"]) == (404, "demo_unavailable")


async def test_a_playing_scenario_says_where_the_story_is(
    database: Database, tokens: TokenFactory, owner: asyncpg.Connection
) -> None:
    await owner.execute(
        "INSERT INTO core.demo_runs (organization_id, kind, requested_at, started_at)"
        " VALUES ($1, 'scenario', now() - $2::interval, now() - $2::interval)",
        data.RIMAC.id,
        timedelta(seconds=75),
    )
    async with api_client(database, tokens, demo_mode=True) as client:
        demo = (
            await client.get("/v1/demo", headers=_as(tokens, SUB_RIMAC_VIEWER, "viewer"))
        ).json()

    run = demo["run"]
    assert (run["status"], run["phase"]) == ("running", "drop")  # the drop comes at 60 s
    assert 74 <= run["elapsed_s"] <= 80
