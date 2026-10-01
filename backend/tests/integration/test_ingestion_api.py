"""VIG-08: POST /v1/readings against the real app and Postgres."""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

import asyncpg
import httpx2
import pytest

from tests.integration.api import api_client
from tests.integration.conftest import Database
from tests.integration.factories import Graph, create_station_with_key
from tests.support.tokens import TokenFactory
from willay.ingestion.domain.api_keys import generate_api_key
from willay.ingestion.domain.readings import MAX_BATCH_SIZE
from willay.shared.clock import SystemClock

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(database: Database, tokens: TokenFactory) -> AsyncIterator[httpx2.AsyncClient]:
    async with api_client(database, tokens) as client:
        yield client


@pytest.fixture
async def station(owner: asyncpg.Connection) -> tuple[Graph, str]:
    return await create_station_with_key(owner)


def _now() -> datetime:
    return SystemClock().now()


def _batch(*measured_at: datetime, value: float = 12.5) -> dict[str, Any]:
    return {"readings": [{"measured_at": m.isoformat(), "value": value} for m in measured_at]}


async def _post(client: httpx2.AsyncClient, key: str | None, body: Any) -> httpx2.Response:
    headers = {"X-Api-Key": key} if key is not None else {}
    return await client.post("/v1/readings", json=body, headers=headers)


async def test_batch_is_stored_and_enqueued_in_the_same_transaction(
    client: httpx2.AsyncClient, station: tuple[Graph, str], owner: asyncpg.Connection
) -> None:
    graph, key = station
    t0 = _now() - timedelta(minutes=1)
    # Deliberately out of order and with another UTC offset: the API normalizes to UTC.
    lima = t0.astimezone(datetime.fromisoformat("2026-01-01T00:00:00-05:00").tzinfo)
    body = _batch(t0 + timedelta(seconds=20), lima, t0 + timedelta(seconds=10))

    response = await _post(client, key, body)

    assert response.status_code == 202, response.text
    assert response.json() == {"received": 3, "stored": 3, "duplicates": 0, "late": 0}
    readings = await owner.fetch(
        "SELECT measured_at, organization_id, quality, received_at FROM ingest.readings "
        "WHERE station_id = $1 ORDER BY measured_at",
        graph.station_id,
    )
    queue = await owner.fetch(
        "SELECT measured_at, organization_id, attempts, available_at, enqueued_at "
        "FROM ingest.evaluation_queue WHERE station_id = $1 ORDER BY measured_at",
        graph.station_id,
    )
    assert [r["measured_at"] for r in readings] == [
        t0,
        t0 + timedelta(seconds=10),
        t0 + timedelta(seconds=20),
    ]
    # The tenant comes from the station that owns the key, not from the request body.
    assert {r["organization_id"] for r in readings} == {graph.organization_id}
    assert {r["quality"] for r in readings} == {"ok"}
    assert [q["measured_at"] for q in queue] == [r["measured_at"] for r in readings]
    assert all(q["attempts"] == 0 and q["available_at"] == q["enqueued_at"] for q in queue)


async def test_resending_readings_does_not_duplicate_them_or_their_queue_rows(
    client: httpx2.AsyncClient, station: tuple[Graph, str], owner: asyncpg.Connection
) -> None:
    graph, key = station
    t0 = _now() - timedelta(minutes=1)
    await _post(client, key, _batch(t0, t0 + timedelta(seconds=10)))

    again = await _post(
        client, key, _batch(t0, t0 + timedelta(seconds=10), t0 + timedelta(seconds=20))
    )

    assert again.json() == {"received": 3, "stored": 1, "duplicates": 2, "late": 0}
    counts = await owner.fetchrow(
        """
        SELECT (SELECT count(*) FROM ingest.readings WHERE station_id = $1) AS readings,
               (SELECT count(*) FROM ingest.evaluation_queue WHERE station_id = $1) AS queued
        """,
        graph.station_id,
    )
    assert counts is not None
    assert (counts["readings"], counts["queued"]) == (3, 3)


async def test_a_full_batch_of_500_is_accepted(
    client: httpx2.AsyncClient, station: tuple[Graph, str]
) -> None:
    _, key = station
    t0 = _now() - timedelta(hours=1)
    body = _batch(*(t0 + timedelta(seconds=i) for i in range(MAX_BATCH_SIZE)))
    response = await _post(client, key, body)
    assert response.json()["stored"] == MAX_BATCH_SIZE


@pytest.mark.parametrize(
    "make_key",
    [
        pytest.param(lambda g, k: None, id="no-key"),
        pytest.param(lambda g, k: "basura", id="malformed"),
        pytest.param(lambda g, k: generate_api_key(g.station_id), id="wrong-secret"),
        pytest.param(lambda g, k: generate_api_key(g.zone_id), id="unknown-station"),
    ],
)
async def test_missing_or_invalid_key_gets_401(
    client: httpx2.AsyncClient, station: tuple[Graph, str], make_key: Any
) -> None:
    graph, key = station
    response = await _post(client, make_key(graph, key), _batch(_now()))
    assert response.status_code == 401, response.text
    assert response.headers["www-authenticate"] == "ApiKey"


async def test_authentication_comes_before_validation(client: httpx2.AsyncClient) -> None:
    # Without a valid key, do not reveal what the body expects: 401, not 422.
    response = await _post(client, "basura", {"no": "es un lote"})
    assert response.status_code == 401


async def test_inactive_station_gets_403(
    client: httpx2.AsyncClient, station: tuple[Graph, str], owner: asyncpg.Connection
) -> None:
    graph, key = station
    await owner.execute(
        "UPDATE core.stations SET status = 'inactive' WHERE id = $1", graph.station_id
    )
    response = await _post(client, key, _batch(_now()))
    assert response.status_code == 403


@pytest.mark.parametrize(
    "make_body",
    [
        pytest.param(lambda now: {"readings": []}, id="empty-batch"),
        pytest.param(
            lambda now: _batch(*(now - timedelta(seconds=i) for i in range(MAX_BATCH_SIZE + 1))),
            id="more-than-500",
        ),
        pytest.param(
            lambda now: {"readings": [{"measured_at": "2026-10-01T08:00:00", "value": 1}]},
            id="no-timezone",
        ),
        pytest.param(
            lambda now: {"readings": [{"measured_at": now.isoformat(), "value": "alto"}]},
            id="non-numeric-value",
        ),
        pytest.param(
            lambda now: {
                "readings": [{"measured_at": now.isoformat(), "value": 1, "station_id": "x"}]
            },
            id="extra-field",
        ),
        pytest.param(lambda now: {}, id="no-readings"),
    ],
)
async def test_invalid_batches_get_422_and_store_nothing(
    client: httpx2.AsyncClient,
    station: tuple[Graph, str],
    owner: asyncpg.Connection,
    make_body: Any,
) -> None:
    graph, key = station
    response = await _post(client, key, make_body(_now()))
    assert response.status_code == 422, response.text
    assert not await owner.fetchval(
        "SELECT count(*) FROM ingest.readings WHERE station_id = $1", graph.station_id
    )


async def test_nan_is_rejected(client: httpx2.AsyncClient, station: tuple[Graph, str]) -> None:
    _, key = station
    # NaN is not standard JSON, but many clients emit it; it is rejected anyway.
    raw = f'{{"readings": [{{"measured_at": "{_now().isoformat()}", "value": NaN}}]}}'
    response = await client.post(
        "/v1/readings",
        content=raw,
        headers={"X-Api-Key": key, "Content-Type": "application/json"},
    )
    assert response.status_code == 422, response.text


async def test_future_readings_are_reported_by_index_and_nothing_is_stored(
    client: httpx2.AsyncClient, station: tuple[Graph, str], owner: asyncpg.Connection
) -> None:
    graph, key = station
    now = _now()
    response = await _post(client, key, _batch(now, now + timedelta(hours=1)))

    assert response.status_code == 422
    assert [e["loc"] for e in response.json()["detail"]] == [["body", "readings", 1, "measured_at"]]
    assert not await owner.fetchval(
        "SELECT count(*) FROM ingest.readings WHERE station_id = $1", graph.station_id
    )
