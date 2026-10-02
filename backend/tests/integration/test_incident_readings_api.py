"""VIG-26: the readings around an incident's opening, with the evidence copy once they expire,
against the real app and Postgres.
"""

import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import asyncpg
import httpx2
import pytest
from uuid_utils.compat import uuid7

from tests.integration.api import api_client, bearer
from tests.integration.conftest import Database
from tests.support.tokens import (
    ISOLATION,
    RIMAC,
    SUB_ISOLATION_ADMIN,
    SUB_RIMAC_VIEWER,
    TokenFactory,
)
from willay.seed import data
from willay.shared.clock import SystemClock

pytestmark = pytest.mark.integration

RULE = next(r for r in data.RULES if r.type == "threshold" and r.organization_id == data.RIMAC.id)


@pytest.fixture
async def client(database: Database, tokens: TokenFactory) -> AsyncIterator[httpx2.AsyncClient]:
    async with api_client(database, tokens) as client:
        yield client


@pytest.fixture
def viewer(tokens: TokenFactory) -> dict[str, str]:
    return bearer(tokens.issue(SUB_RIMAC_VIEWER, organization=RIMAC, roles=("viewer",)))


async def _incident(owner: asyncpg.Connection, opened_at: datetime) -> str:
    """A threshold incident whose opened event keeps a copy of two readings."""
    incident_id = uuid7()
    await owner.execute(
        """
        INSERT INTO core.incidents (id, organization_id, zone_id, rule_id, station_id, severity,
                                    trigger_value, dedup_key, opened_at, level_started_at)
        VALUES ($1, $2, $3, $4, $5, 'warning', 4.6, $6, $7, $7)
        """,
        incident_id, data.RIMAC.id, RULE.zone_id, RULE.id, RULE.station_id,
        f"test:{uuid4()}", opened_at,
    )  # fmt: skip
    payload: dict[str, Any] = {
        "rule_type": "threshold",
        "rule_params": RULE.params,
        "trigger_value": 4.6,
        "readings": [
            {"measured_at": (opened_at - timedelta(seconds=10)).isoformat(), "value": 4.2},
            {"measured_at": opened_at.isoformat(), "value": 4.6},
        ],
    }
    await owner.execute(
        "INSERT INTO core.incident_events (incident_id, organization_id, occurred_at,"
        " event_type, actor_type, payload) VALUES ($1, $2, $3, 'opened', 'system', $4)",
        incident_id, data.RIMAC.id, opened_at, json.dumps(payload),
    )  # fmt: skip
    return str(incident_id)


async def _reading(
    owner: asyncpg.Connection, measured_at: datetime, value: float, quality: str = "ok"
) -> None:
    await owner.execute(
        "INSERT INTO ingest.readings (station_id, organization_id, measured_at, received_at,"
        " value, quality) VALUES ($1, $2, $3, $3, $4, $5)",
        RULE.station_id, data.RIMAC.id, measured_at, value, quality,
    )  # fmt: skip


async def test_the_chart_gets_the_ok_readings_of_its_window_and_the_threshold(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, viewer: dict[str, str]
) -> None:
    # Odd microseconds: no clash with readings other tests store for the same station.
    opened = SystemClock().now() - timedelta(minutes=90, microseconds=uuid4().int % 999_999)
    incident_id = await _incident(owner, opened)
    inside = [(-50, 1001.5), (-10, 1002.5), (10, 1003.5), (60, 1004.5)]
    for minutes, value in inside:
        await _reading(owner, opened + timedelta(minutes=minutes), value)
    await _reading(owner, opened - timedelta(minutes=70), 1000.5)  # before the window
    await _reading(owner, opened - timedelta(minutes=20), 1009.5, quality="late")

    response = await client.get(f"/v1/incidents/{incident_id}/readings", headers=viewer)

    assert response.status_code == 200, response.text
    chart = response.json()
    assert (chart["station_code"], chart["unit"], chart["source"]) == (
        "RIM-CHO-01",
        "m",
        "readings",
    )
    values = [r["value"] for r in chart["readings"]]
    mine = [v for v in values if v > 1000]
    assert mine == [1001.5, 1002.5, 1003.5, 1004.5]  # in order, without the late one
    assert chart["threshold"] == {"operator": "gt", "value": 3.5}


async def test_once_the_readings_expired_the_chart_shows_the_evidence_copy(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, viewer: dict[str, str]
) -> None:
    # Past the 180-day retention: nothing stored is left in its window.
    opened = SystemClock().now() - timedelta(days=400, microseconds=uuid4().int % 999_999)
    incident_id = await _incident(owner, opened)

    chart = (await client.get(f"/v1/incidents/{incident_id}/readings", headers=viewer)).json()

    assert chart["source"] == "evidence"
    assert [r["value"] for r in chart["readings"]] == [4.2, 4.6]


async def test_another_organization_gets_404(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, tokens: TokenFactory
) -> None:
    incident_id = await _incident(owner, SystemClock().now() - timedelta(hours=1))
    other = bearer(tokens.issue(SUB_ISOLATION_ADMIN, organization=ISOLATION, roles=("admin",)))
    response = await client.get(f"/v1/incidents/{incident_id}/readings", headers=other)
    assert response.status_code == 404
