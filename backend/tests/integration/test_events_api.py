"""VIG-25: the `/v1/events` SSE channel against real Postgres and a real uvicorn server."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any
from uuid import UUID

import asyncpg
import httpx2
import pytest

from tests.integration.api import bearer, serve_api
from tests.integration.conftest import Database
from tests.support.tokens import (
    ISOLATION,
    RIMAC,
    SUB_ISOLATION_ADMIN,
    SUB_RIMAC_OPERATOR,
    TokenFactory,
)
from willay.seed import data

pytestmark = pytest.mark.integration


class EventStream:
    """Reads an SSE stream event by event, skipping keepalive comments."""

    def __init__(self, response: httpx2.Response) -> None:
        self._lines = response.aiter_lines()

    async def next(self) -> tuple[str, dict[str, Any]] | None:
        """The next event, or None if the server closed the stream. The caller sets the
        wait limit with `asyncio.timeout`."""
        event, data = "message", ""
        async for line in self._lines:
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data = line.removeprefix("data:").strip()
            elif line == "" and data:
                return event, json.loads(data)
        return None


@asynccontextmanager
async def stream(base_url: str, token: str) -> AsyncIterator[EventStream]:
    async with (
        httpx2.AsyncClient(base_url=base_url, timeout=None) as client,
        client.stream("GET", "/v1/events", headers=bearer(token)) as response,
    ):
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = EventStream(response)
        async with asyncio.timeout(5):
            assert await events.next() == ("ready", {})
        yield events


async def _heartbeat(owner: asyncpg.Connection, station: UUID, value: float) -> None:
    """Like ingestion: the heartbeat upsert is what fires the notification."""
    await owner.execute(
        """
        INSERT INTO ingest.station_heartbeats
            (station_id, last_seen_at, last_measured_at, last_value, updated_at)
        VALUES ($1, now(), now(), $2, now())
        ON CONFLICT (station_id) DO UPDATE SET
            last_seen_at = EXCLUDED.last_seen_at, last_measured_at = EXCLUDED.last_measured_at,
            last_value = EXCLUDED.last_value, updated_at = EXCLUDED.updated_at
        """,
        station,
        value,
    )


async def test_each_organization_only_hears_its_own_events_within_two_seconds(
    database: Database, tokens: TokenFactory, owner: asyncpg.Connection
) -> None:
    rimac_token = tokens.issue(SUB_RIMAC_OPERATOR, organization=RIMAC)
    other_token = tokens.issue(SUB_ISOLATION_ADMIN, organization=ISOLATION, roles=("admin",))
    async with (
        serve_api(database, tokens) as base_url,
        stream(base_url, rimac_token) as rimac,
        stream(base_url, other_token) as other,
    ):
        await _heartbeat(owner, data.S_CHACLACAYO, 41.5)
        async with asyncio.timeout(2):  # SPEC: update < 2 s
            event = await rimac.next()
        assert event is not None
        kind, payload = event
        assert (kind, payload["station_id"], payload["last_value"]) == (
            "station",
            str(data.S_CHACLACAYO),
            41.5,
        )
        assert "organization_id" not in payload  # the browser already knows whose it is

        # The other organization did not hear Rímac's heartbeat: the first thing it gets is its own.
        await _heartbeat(owner, data.S_AIS_1, 2.0)
        async with asyncio.timeout(2):
            event = await other.next()
        assert event is not None
        assert event[1]["station_id"] == str(data.S_AIS_1)
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(1):
                await rimac.next()  # and Rímac did not hear the isolation org's one


async def test_the_stream_ends_when_its_token_expires(
    database: Database, tokens: TokenFactory
) -> None:
    token = tokens.issue(SUB_RIMAC_OPERATOR, organization=RIMAC, lifetime=timedelta(seconds=3))
    async with serve_api(database, tokens) as base_url, stream(base_url, token) as events:
        # The server closes it on its own; the client reconnects with a valid token.
        async with asyncio.timeout(6):
            assert await events.next() is None


@pytest.mark.parametrize(
    ("roles", "status"),
    [(None, 401), ((), 403)],
    ids=["no-token", "no-role"],
)
async def test_no_token_or_no_role_gets_no_stream(
    database: Database, tokens: TokenFactory, roles: tuple[str, ...] | None, status: int
) -> None:
    token = (
        None if roles is None else tokens.issue(SUB_RIMAC_OPERATOR, organization=RIMAC, roles=roles)
    )
    async with serve_api(database, tokens) as base_url, httpx2.AsyncClient() as client:
        response = await client.get(f"{base_url}/v1/events", headers=bearer(token))
    assert response.status_code == status
