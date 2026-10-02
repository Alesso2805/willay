"""VIG-27: rule preview against the real app and Postgres, on a zone and station of its own so
no other test's readings get in the way."""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx2
import pytest
from uuid_utils.compat import uuid7

from tests.integration.api import api_client, bearer
from tests.integration.conftest import Database
from tests.support.tokens import (
    RIMAC,
    SUB_RIMAC_OPERATOR,
    SUB_RIMAC_VIEWER,
    TokenFactory,
)
from willay.seed import data
from willay.shared.clock import SystemClock

pytestmark = pytest.mark.integration

URL = "/v1/rules/preview"
# A drop of 51 m3/s, a partial recovery, then the station goes quiet.
VALUES = [85.0, 84.5, 34.0, 60.0, 61.0, 61.5, 62.0]


@pytest.fixture
async def client(database: Database, tokens: TokenFactory) -> AsyncIterator[httpx2.AsyncClient]:
    async with api_client(database, tokens) as client:
        yield client


@pytest.fixture
def operator(tokens: TokenFactory) -> dict[str, str]:
    return bearer(tokens.issue(SUB_RIMAC_OPERATOR, organization=RIMAC, roles=("operator",)))


@pytest.fixture
async def place(owner: asyncpg.Connection) -> dict[str, Any]:
    """A Rímac zone with one station that reported once a minute and then stopped, 20 min ago."""
    zone_id, station_id = uuid7(), uuid7()
    suffix = uuid4().hex[:6]
    await owner.execute(
        """
        INSERT INTO core.risk_zones (id, organization_id, name, risk_level, geom)
        VALUES ($1, $2, $3, 'low', ST_GeomFromText('MULTIPOLYGON(((-76.1 -11.1, -76.0 -11.1,
                -76.0 -11.2, -76.1 -11.2, -76.1 -11.1)))', 4326))
        """,
        zone_id, data.RIMAC.id, f"Vista previa {suffix}",
    )  # fmt: skip
    await owner.execute(
        """
        INSERT INTO core.stations (id, organization_id, code, name, variable, unit, location,
                                   source, expected_interval_s, silence_multiplier,
                                   api_key_hash, api_key_rotated_at)
        VALUES ($1, $2, $3, 'Vista previa', 'discharge', 'm3/s',
                ST_SetSRID(ST_MakePoint(-76.05, -11.15), 4326), 'simulator', 60, 3, 'x', now())
        """,
        station_id, data.RIMAC.id, f"PRV-{suffix}",
    )  # fmt: skip
    await owner.execute(
        "INSERT INTO core.zone_stations (zone_id, station_id, position) VALUES ($1, $2, 'in_zone')",
        zone_id, station_id,
    )  # fmt: skip
    now = SystemClock().now().replace(microsecond=0)
    first = now - timedelta(minutes=20 + len(VALUES) - 1)
    times = [first + timedelta(minutes=i) for i in range(len(VALUES))]
    for at, value in zip(times, VALUES, strict=True):
        await owner.execute(
            "INSERT INTO ingest.readings (station_id, organization_id, measured_at, received_at,"
            " value, quality) VALUES ($1, $2, $3, $3, $4, 'ok')",
            station_id, data.RIMAC.id, at, value,
        )  # fmt: skip
    return {"zone_id": str(zone_id), "station_id": str(station_id), "times": times}


def _at(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


async def test_only_who_manages_rules_previews_them(
    client: httpx2.AsyncClient, tokens: TokenFactory, place: dict[str, Any]
) -> None:
    viewer = bearer(tokens.issue(SUB_RIMAC_VIEWER, organization=RIMAC, roles=("viewer",)))
    body = {"type": "silence", "zone_id": place["zone_id"]}
    assert (await client.post(URL, json=body, headers=viewer)).status_code == 403


async def test_a_drop_rule_marks_the_reading_that_would_have_opened_the_incident(
    client: httpx2.AsyncClient, operator: dict[str, str], place: dict[str, Any]
) -> None:
    body = {
        "type": "rate_of_change",
        "zone_id": place["zone_id"],
        "station_id": place["station_id"],
        "params": {"direction": "down", "delta": 40, "window_minutes": 10},
    }
    response = await client.post(URL, json=body, headers=operator)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert _at(preview["until"]) - _at(preview["since"]) == timedelta(hours=24)
    [station] = preview["stations"]
    assert station["station"]["unit"] == "m3/s"
    assert [r["value"] for r in station["readings"]] == VALUES
    assert station["truncated"] is False
    # Once at 34, though the drop stays in the window for the next readings.
    assert [(_at(f["at"]), f["value"]) for f in station["firings"]] == [(place["times"][2], 34.0)]


async def test_a_threshold_marks_each_run_of_n_readings(
    client: httpx2.AsyncClient, operator: dict[str, str], place: dict[str, Any]
) -> None:
    body = {
        "type": "threshold",
        "zone_id": place["zone_id"],
        "station_id": place["station_id"],
        "params": {"operator": "lt", "value": 61, "consecutive": 2},
    }
    firings = (await client.post(URL, json=body, headers=operator)).json()["stations"][0]["firings"]
    # 34 and 60 are a run of two below 61; 61.0 is not below it (exact boundary).
    assert [(_at(f["at"]), f["value"]) for f in firings] == [(place["times"][3], 60.0)]


async def test_a_zone_wide_silence_rule_marks_when_the_station_went_quiet(
    client: httpx2.AsyncClient, operator: dict[str, str], place: dict[str, Any]
) -> None:
    body = {"type": "silence", "zone_id": place["zone_id"]}
    [station] = (await client.post(URL, json=body, headers=operator)).json()["stations"]
    # Silent 3 * 60 s after its last report.
    expected = place["times"][-1] + timedelta(seconds=180)
    assert [(_at(f["at"]), f["value"]) for f in station["firings"]] == [(expected, None)]


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"zone_id": str(data.Z_TEST)}, "zone_id"),  # another organization's zone
        ({"station_id": str(data.S_QUIRIO)}, "station_id"),  # not a station of this zone
        ({"station_id": None}, "station_id"),  # a threshold needs its station
        ({"params": {"operator": "lt", "value": 1, "consecutive": 0}}, "consecutive"),
    ],
)
async def test_an_invalid_draft_gets_422_on_its_field(
    client: httpx2.AsyncClient,
    operator: dict[str, str],
    place: dict[str, Any],
    changes: dict[str, Any],
    field: str,
) -> None:
    body = {
        "type": "threshold",
        "zone_id": place["zone_id"],
        "station_id": place["station_id"],
        "params": {"operator": "lt", "value": 1, "consecutive": 1},
    } | changes
    response = await client.post(URL, json=body, headers=operator)
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"][-1] == field


async def test_nothing_is_written(
    client: httpx2.AsyncClient,
    owner: asyncpg.Connection,
    operator: dict[str, str],
    place: dict[str, Any],
) -> None:
    before = await owner.fetchval("SELECT count(*) FROM core.audit_log")
    await client.post(URL, json={"type": "silence", "zone_id": place["zone_id"]}, headers=operator)
    assert await owner.fetchval("SELECT count(*) FROM core.audit_log") == before
    assert not await owner.fetchval(
        "SELECT count(*) FROM core.rules WHERE zone_id = $1", UUID(place["zone_id"])
    )
