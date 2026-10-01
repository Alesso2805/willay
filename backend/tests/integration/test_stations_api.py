"""VIG-13: station CRUD, zone assignment and API key rotation."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx2
import pytest

from tests.integration.api import api_client, bearer
from tests.integration.conftest import Database
from tests.support.tokens import (
    ISOLATION,
    RIMAC,
    SUB_ISOLATION_ADMIN,
    SUB_RIMAC_OPERATOR,
    SUB_RIMAC_VIEWER,
    TokenFactory,
)
from willay.seed import data
from willay.shared.clock import SystemClock

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(database: Database, tokens: TokenFactory) -> AsyncIterator[httpx2.AsyncClient]:
    async with api_client(database, tokens) as client:
        yield client


@pytest.fixture
def operator(tokens: TokenFactory) -> dict[str, str]:
    return bearer(tokens.issue(SUB_RIMAC_OPERATOR, organization=RIMAC, roles=("operator",)))


@pytest.fixture
def viewer(tokens: TokenFactory) -> dict[str, str]:
    return bearer(tokens.issue(SUB_RIMAC_VIEWER, organization=RIMAC, roles=("viewer",)))


@pytest.fixture
def other_org_admin(tokens: TokenFactory) -> dict[str, str]:
    return bearer(tokens.issue(SUB_ISOLATION_ADMIN, organization=ISOLATION, roles=("admin",)))


def _station(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "code": f"tst-{uuid4().hex[:6]}",
        "name": "Estación de prueba",
        "variable": "discharge",
        "location": {"type": "Point", "coordinates": [-76.70, -11.93]},
        "expected_interval_s": 10,
        "zones": [{"zone_id": str(data.Z_CHOSICA), "position": "downstream"}],
    }
    body.update(overrides)
    return body


def _editable(station: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """PUT body built from a fetched station (without the code or read-only fields)."""
    keys = ("name", "variable", "location", "source", "expected_interval_s",
            "silence_multiplier", "status", "zones")  # fmt: skip
    return {**{k: station[k] for k in keys}, **overrides}


async def _create(client: httpx2.AsyncClient, headers: dict[str, str], **overrides: Any) -> Any:
    response = await client.post("/v1/stations", json=_station(**overrides), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _send_reading(client: httpx2.AsyncClient, api_key: str) -> int:
    body = {"readings": [{"measured_at": SystemClock().now().isoformat(), "value": 80.0}]}
    response = await client.post("/v1/readings", json=body, headers={"X-Api-Key": api_key})
    return response.status_code


async def test_created_station_gets_a_working_key_shown_once(
    client: httpx2.AsyncClient, operator: dict[str, str]
) -> None:
    response = await client.post(
        "/v1/stations", json=_station(code="  tst-lower "), headers=operator
    )

    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    created = response.json()
    station = created["station"]
    assert station["code"] == "TST-LOWER"  # normalized
    assert station["unit"] == "m3/s"  # derived from the variable
    assert station["zones"] == [{"zone_id": str(data.Z_CHOSICA), "position": "downstream"}]
    assert station["has_zone"] is True
    # The returned key works right away for ingestion...
    assert await _send_reading(client, created["api_key"]) == 202
    # ...and never shows up again in any later read.
    fetched = (await client.get(f"/v1/stations/{station['id']}", headers=operator)).json()
    assert "api_key" not in fetched
    assert fetched["heartbeat"]["last_value"] == 80.0


async def test_rotating_the_key_revokes_the_old_one_at_once(
    client: httpx2.AsyncClient, operator: dict[str, str], owner: asyncpg.Connection
) -> None:
    created = await _create(client, operator)
    old_key, station_id = created["api_key"], created["station"]["id"]

    response = await client.post(f"/v1/stations/{station_id}/api-key", headers=operator)

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    new_key = response.json()["api_key"]
    assert new_key != old_key
    assert await _send_reading(client, old_key) == 401
    assert await _send_reading(client, new_key) == 202

    # Neither the key nor its hash ends up in the audit log.
    audit = await owner.fetch(
        "SELECT action, before::text AS before, after::text AS after FROM core.audit_log "
        "WHERE entity_type = 'station' AND entity_id = $1 ORDER BY id",
        UUID(station_id),
    )
    assert [a["action"] for a in audit] == ["create", "rotate_api_key"]
    dumped = " ".join(f"{a['before']} {a['after']}" for a in audit)
    assert old_key not in dumped
    assert new_key not in dumped
    assert "argon2" not in dumped


async def test_duplicate_code_in_the_same_organization_gets_409(
    client: httpx2.AsyncClient, operator: dict[str, str], other_org_admin: dict[str, str]
) -> None:
    code = f"dup-{uuid4().hex[:6]}"
    await _create(client, operator, code=code)

    again = await client.post("/v1/stations", json=_station(code=code.upper()), headers=operator)
    assert again.status_code == 409

    # The same code in another organization is fine: uniqueness is per tenant.
    other = _station(code=code, zones=[])
    assert (
        await client.post("/v1/stations", json=other, headers=other_org_admin)
    ).status_code == 201


FOREIGN_ZONE = [{"zone_id": str(data.Z_TEST), "position": "in_zone"}]
UNKNOWN_ZONE = [{"zone_id": str(uuid4()), "position": "in_zone"}]
REPEATED_ZONE = [
    {"zone_id": str(data.Z_CHOSICA), "position": "upstream"},
    {"zone_id": str(data.Z_CHOSICA), "position": "in_zone"},
]
TOKYO_SWAPPED = {"type": "Point", "coordinates": [-11.9, 139.6]}


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        pytest.param({"zones": FOREIGN_ZONE}, "zones", id="zone-from-other-org"),
        pytest.param({"zones": UNKNOWN_ZONE}, "zones", id="unknown-zone"),
        pytest.param({"zones": REPEATED_ZONE}, "zones", id="repeated-zone"),
        pytest.param({"code": "con espacio"}, "code", id="invalid-code"),
        pytest.param({"location": TOKYO_SWAPPED}, "location", id="out-of-range"),
    ],
)
async def test_invalid_stations_get_422(
    client: httpx2.AsyncClient, operator: dict[str, str], overrides: dict[str, Any], field: str
) -> None:
    response = await client.post("/v1/stations", json=_station(**overrides), headers=operator)
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"] == ["body", field]


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"variable": "temperature"}, id="unknown-variable"),
        pytest.param({"expected_interval_s": 1}, id="interval-too-short"),
        pytest.param({"silence_multiplier": 0}, id="zero-k"),
        pytest.param({"unit": "cm"}, id="unit-not-editable"),
    ],
)
async def test_invalid_attributes_get_422(
    client: httpx2.AsyncClient, operator: dict[str, str], overrides: dict[str, Any]
) -> None:
    response = await client.post("/v1/stations", json=_station(**overrides), headers=operator)
    assert response.status_code == 422, response.text


async def test_put_changes_zones_and_keeps_the_code(
    client: httpx2.AsyncClient, operator: dict[str, str]
) -> None:
    station = (await _create(client, operator))["station"]
    body = _editable(
        station,
        name="Renombrada",
        zones=[
            {"zone_id": str(data.Z_CHOSICA), "position": "upstream"},
            {"zone_id": str(data.Z_CHACLACAYO), "position": "in_zone"},
        ],
    )

    response = await client.put(f"/v1/stations/{station['id']}", json=body, headers=operator)

    assert response.status_code == 200, response.text
    updated = response.json()
    assert (updated["name"], updated["code"]) == ("Renombrada", station["code"])
    assert {z["position"] for z in updated["zones"]} == {"upstream", "in_zone"}
    # The code cannot be sent in a PUT: the body schema rejects it.
    with_code = {**body, "code": "OTRO-01"}
    rejected = await client.put(f"/v1/stations/{station['id']}", json=with_code, headers=operator)
    assert rejected.status_code == 422


async def test_stations_without_zone_are_marked(
    client: httpx2.AsyncClient, viewer: dict[str, str]
) -> None:
    stations = (await client.get("/v1/stations", headers=viewer)).json()
    by_id = {s["id"]: s for s in stations}
    assert by_id[str(data.S_UNZONED)]["has_zone"] is False
    assert by_id[str(data.S_CHACLACAYO)]["has_zone"] is True


async def test_delete_deactivates_and_ingestion_answers_403(
    client: httpx2.AsyncClient, operator: dict[str, str]
) -> None:
    created = await _create(client, operator)
    station_id = created["station"]["id"]

    assert (await client.delete(f"/v1/stations/{station_id}", headers=operator)).status_code == 204
    assert await _send_reading(client, created["api_key"]) == 403
    active = {s["id"] for s in (await client.get("/v1/stations", headers=operator)).json()}
    assert station_id not in active


async def test_viewer_reads_and_other_tenants_get_404(
    client: httpx2.AsyncClient,
    operator: dict[str, str],
    viewer: dict[str, str],
    other_org_admin: dict[str, str],
) -> None:
    station = (await _create(client, operator))["station"]
    url = f"/v1/stations/{station['id']}"

    assert (await client.get(url, headers=viewer)).status_code == 200
    assert (await client.post("/v1/stations", json=_station(), headers=viewer)).status_code == 403
    assert (await client.post(f"{url}/api-key", headers=viewer)).status_code == 403

    assert (await client.get(url, headers=other_org_admin)).status_code == 404
    assert (
        await client.put(url, json=_editable(station), headers=other_org_admin)
    ).status_code == 404
    assert (await client.post(f"{url}/api-key", headers=other_org_admin)).status_code == 404
    other_ids = {
        s["id"] for s in (await client.get("/v1/stations", headers=other_org_admin)).json()
    }
    assert station["id"] not in other_ids
