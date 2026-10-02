"""VIG-39: failed readings against the real app and Postgres: permissions per role, isolation,
audit, the evaluator woken up, and the reprocessed reading ending up evaluated."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.api import api_client, bearer
from tests.integration.conftest import Database
from tests.support.tokens import (
    ISOLATION,
    RIMAC,
    SUB_ISOLATION_ADMIN,
    SUB_RIMAC_ADMIN,
    SUB_RIMAC_OPERATOR,
    SUB_RIMAC_RESPONDER,
    SUB_RIMAC_VIEWER,
    TokenFactory,
)
from willay.alerts.application.planning import AlertPlanner
from willay.alerts.infrastructure.sql_alerts import SqlAlertRepository
from willay.incidents.infrastructure.sql_incidents import SqlIncidentStore
from willay.rules.application.evaluate import process_batch
from willay.rules.application.rule_evaluator import RuleEvaluator
from willay.rules.infrastructure.pg_queue import PostgresEvaluationQueue
from willay.rules.infrastructure.sql_rules import SqlReadingHistory, SqlRuleRepository
from willay.seed import data
from willay.shared import notifications
from willay.shared.clock import SystemClock
from willay.shared.db import create_engine

pytestmark = pytest.mark.integration

URL = "/v1/failed-readings"


@pytest.fixture
async def client(database: Database, tokens: TokenFactory) -> AsyncIterator[httpx2.AsyncClient]:
    async with api_client(database, tokens) as client:
        yield client


@pytest.fixture
async def engine(database: Database) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


def _as(tokens: TokenFactory, sub: UUID, role: str, organization: Any = RIMAC) -> dict[str, str]:
    return bearer(tokens.issue(sub, organization=organization, roles=(role,)))


@pytest.fixture
def operator(tokens: TokenFactory) -> dict[str, str]:
    return _as(tokens, SUB_RIMAC_OPERATOR, "operator")


async def _failed_reading(owner: asyncpg.Connection, value: float = 12.5) -> int:
    """A Rímac reading the evaluator gave up on, at a time no other test uses. The station has
    no zone, so evaluating it opens nothing."""
    now = SystemClock().now()
    measured_at = now - timedelta(hours=2, microseconds=uuid4().int % 10**9)
    await owner.execute(
        "INSERT INTO ingest.readings (station_id, organization_id, measured_at, received_at,"
        " value, quality) VALUES ($1, $2, $3, $3, $4, 'ok')",
        data.S_UNZONED, data.RIMAC.id, measured_at, value,
    )  # fmt: skip
    queue_id: int = await owner.fetchval(
        "INSERT INTO ingest.evaluation_queue (station_id, measured_at, organization_id,"
        " enqueued_at, available_at, attempts, last_error, failed_at)"
        " VALUES ($1, $2, $3, $4, $4, 5, 'regla con parámetros inválidos', $4) RETURNING id",
        data.S_UNZONED, measured_at, data.RIMAC.id, now,
    )  # fmt: skip
    return queue_id


@pytest.mark.parametrize(
    ("sub", "role", "expected"),
    [
        (SUB_RIMAC_VIEWER, "viewer", 403),
        (SUB_RIMAC_RESPONDER, "responder", 403),
        (SUB_RIMAC_OPERATOR, "operator", 200),
        (SUB_RIMAC_ADMIN, "admin", 200),
    ],
)
async def test_only_operator_and_admin_see_and_reprocess(
    client: httpx2.AsyncClient, tokens: TokenFactory, sub: UUID, role: str, expected: int
) -> None:
    headers = _as(tokens, sub, role)
    assert (await client.get(URL, headers=headers)).status_code == expected
    assert (await client.get(f"{URL}/count", headers=headers)).status_code == expected
    reprocessed = await client.post(f"{URL}/reprocess", json={"ids": [0]}, headers=headers)
    assert reprocessed.status_code == expected


async def test_a_failed_reading_is_listed_with_its_station_value_and_error(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, operator: dict[str, str]
) -> None:
    before = (await client.get(f"{URL}/count", headers=operator)).json()["count"]
    queue_id = await _failed_reading(owner, value=12.5)

    assert (await client.get(f"{URL}/count", headers=operator)).json() == {"count": before + 1}
    listed = (await client.get(URL, headers=operator)).json()
    mine = next(r for r in listed if r["id"] == queue_id)
    assert mine | {"measured_at": None, "failed_at": None} == {
        "id": queue_id,
        "station_id": str(data.S_UNZONED),
        "station_code": "RIM-TMP-01",
        "station_name": mine["station_name"],
        "measured_at": None,
        "value": 12.5,
        "attempts": 5,
        "failed_at": None,
        "last_error": "regla con parámetros inválidos",
    }
    failed_times = [r["failed_at"] for r in listed]
    assert failed_times == sorted(failed_times, reverse=True)  # most recent failure first


async def test_another_organization_neither_sees_nor_reprocesses_them(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, tokens: TokenFactory
) -> None:
    queue_id = await _failed_reading(owner)
    other = _as(tokens, SUB_ISOLATION_ADMIN, "admin", organization=ISOLATION)
    assert queue_id not in [r["id"] for r in (await client.get(URL, headers=other)).json()]
    reprocessed = await client.post(f"{URL}/reprocess", json={"ids": [queue_id]}, headers=other)
    assert reprocessed.json() == {"reprocessed": 0}
    still = await owner.fetchval(
        "SELECT failed_at FROM ingest.evaluation_queue WHERE id = $1", queue_id
    )
    assert still is not None


async def test_a_reprocessed_reading_ends_up_evaluated(
    client: httpx2.AsyncClient,
    owner: asyncpg.Connection,
    engine: AsyncEngine,
    database: Database,
    operator: dict[str, str],
) -> None:
    queue_id = await _failed_reading(owner)
    measured_at = await owner.fetchval(
        "SELECT measured_at FROM ingest.evaluation_queue WHERE id = $1", queue_id
    )
    heard: dict[str, list[str]] = {notifications.EVENTS: [], notifications.EVALUATION_QUEUE: []}
    both = asyncio.Event()

    def on_notice(_conn: object, _pid: int, channel: str, payload: object) -> None:
        heard[channel].append(str(payload))
        if all(heard.values()):
            both.set()

    listener = await asyncpg.connect(database.app_dsn)
    for channel in heard:
        await listener.add_listener(channel, on_notice)
    try:
        response = await client.post(
            f"{URL}/reprocess", json={"ids": [queue_id, queue_id]}, headers=operator
        )
        assert response.json() == {"reprocessed": 1}
        async with asyncio.timeout(5):
            await both.wait()  # the dashboard is told, and the evaluator woken up
    finally:
        await listener.close()
    notices = [json.loads(p) for p in heard[notifications.EVENTS]]
    assert {"organization_id": str(data.RIMAC.id), "type": "failed_readings"} in notices

    row = await owner.fetchrow(
        "SELECT attempts, failed_at FROM ingest.evaluation_queue WHERE id = $1", queue_id
    )
    assert row is not None
    assert (row["attempts"], row["failed_at"]) == (0, None)
    again = await client.post(f"{URL}/reprocess", json={"ids": [queue_id]}, headers=operator)
    assert again.json() == {"reprocessed": 0}  # already back in the queue: not audited twice
    audit = await owner.fetch(
        "SELECT actor_id, after FROM core.audit_log WHERE entity_type = 'station'"
        " AND entity_id = $1 AND action = 'readings_reprocessed' AND after::text LIKE $2",
        data.S_UNZONED, f"%{measured_at.isoformat()}%",
    )  # fmt: skip
    assert [r["actor_id"] for r in audit] == [SUB_RIMAC_OPERATOR]
    [reading] = json.loads(audit[0]["after"])["readings"]
    assert reading["last_error"] == "regla con parámetros inválidos"

    # The evaluator takes it like any other row: the shared queue may hold other tests' rows.
    clock = SystemClock()
    queue = PostgresEvaluationQueue(engine, clock)
    evaluator = RuleEvaluator(
        SqlRuleRepository(), SqlReadingHistory(), SqlIncidentStore(), clock,
        alerts=AlertPlanner(SqlAlertRepository()),
    )  # fmt: skip
    async with asyncio.timeout(20):
        while await owner.fetchval(
            "SELECT count(*) FROM ingest.evaluation_queue WHERE id = $1", queue_id
        ):
            await process_batch(queue, evaluator, engine.begin, limit=50)
    evaluated = await owner.fetchval(
        "SELECT evaluated_at FROM ingest.readings WHERE station_id = $1 AND measured_at = $2",
        data.S_UNZONED, measured_at,
    )  # fmt: skip
    assert evaluated is not None


async def test_reprocessing_needs_at_least_one_id(
    client: httpx2.AsyncClient, operator: dict[str, str]
) -> None:
    response = await client.post(f"{URL}/reprocess", json={"ids": []}, headers=operator)
    assert response.status_code == 422
