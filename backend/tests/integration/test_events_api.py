"""VIG-25: el canal SSE `/v1/events` contra Postgres real y un servidor uvicorn real."""

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
    AISLAMIENTO,
    RIMAC,
    SUB_AISLAMIENTO_ADMIN,
    SUB_RIMAC_OPERATOR,
    TokenFactory,
)
from vigia.seed import data

pytestmark = pytest.mark.integration


class EventStream:
    """Lee un stream SSE evento por evento; ignora los comentarios de keepalive."""

    def __init__(self, response: httpx2.Response) -> None:
        self._lines = response.aiter_lines()

    async def next(self) -> tuple[str, dict[str, Any]] | None:
        """El siguiente evento, o None si el servidor cerró el stream. Quien llama pone
        el límite de espera con `asyncio.timeout`."""
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
    """Como la ingesta: el upsert del latido es lo que dispara el aviso."""
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
    other_token = tokens.issue(SUB_AISLAMIENTO_ADMIN, organization=AISLAMIENTO, roles=("admin",))
    async with (
        serve_api(database, tokens) as base_url,
        stream(base_url, rimac_token) as rimac,
        stream(base_url, other_token) as other,
    ):
        await _heartbeat(owner, data.S_CHACLACAYO, 41.5)
        async with asyncio.timeout(2):  # SPEC: actualización < 2 s
            event = await rimac.next()
        assert event is not None
        kind, payload = event
        assert (kind, payload["station_id"], payload["last_value"]) == (
            "station",
            str(data.S_CHACLACAYO),
            41.5,
        )
        assert "organization_id" not in payload  # el navegador ya sabe de quién es

        # La otra organización no oyó el latido de Rímac: lo primero que recibe es el suyo.
        await _heartbeat(owner, data.S_AIS_1, 2.0)
        async with asyncio.timeout(2):
            event = await other.next()
        assert event is not None
        assert event[1]["station_id"] == str(data.S_AIS_1)
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(1):
                await rimac.next()  # y Rímac no oyó el de aislamiento


async def test_the_stream_ends_when_its_token_expires(
    database: Database, tokens: TokenFactory
) -> None:
    token = tokens.issue(SUB_RIMAC_OPERATOR, organization=RIMAC, lifetime=timedelta(seconds=3))
    async with serve_api(database, tokens) as base_url, stream(base_url, token) as events:
        # Cierra por su cuenta: el cliente se reconecta con un token vigente.
        async with asyncio.timeout(6):
            assert await events.next() is None


@pytest.mark.parametrize(
    ("roles", "status"),
    [(None, 401), ((), 403)],
    ids=["sin-token", "sin-rol"],
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
