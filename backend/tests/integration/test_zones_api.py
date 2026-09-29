"""VIG-12: CRUD de zonas de riesgo contra la app y PostGIS reales."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx2
import pytest

from tests.integration.api import api_client, bearer
from tests.integration.conftest import Database
from tests.support.tokens import (
    AISLAMIENTO,
    RIMAC,
    SUB_AISLAMIENTO_ADMIN,
    SUB_RIMAC_OPERATOR,
    SUB_RIMAC_VIEWER,
    TokenFactory,
)
from vigia.seed import data

pytestmark = pytest.mark.integration

SQUARE = [[-76.70, -11.90], [-76.60, -11.90], [-76.60, -12.00], [-76.70, -12.00], [-76.70, -11.90]]
# "Corbata": dos lados se cruzan. La estructura es correcta (anillo cerrado, 5 posiciones),
# así que solo la topología de PostGIS puede rechazarlo.
BOW_TIE = [[-76.70, -11.90], [-76.60, -12.00], [-76.60, -11.90], [-76.70, -12.00], [-76.70, -11.90]]


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
    return bearer(tokens.issue(SUB_AISLAMIENTO_ADMIN, organization=AISLAMIENTO, roles=("admin",)))


def _zone(ring: list[list[float]] = SQUARE, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": f"Zona {uuid4().hex[:8]}",
        "risk_level": "high",
        "population_estimate": 1200,
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }
    body.update(overrides)
    return body


async def _create(client: httpx2.AsyncClient, headers: dict[str, str], **overrides: Any) -> Any:
    response = await client.post("/v1/zones", json=_zone(**overrides), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_operator_creates_a_zone_and_it_is_audited(
    client: httpx2.AsyncClient, operator: dict[str, str], owner: asyncpg.Connection
) -> None:
    body = _zone(description="Quebrada Quirio")
    response = await client.post("/v1/zones", json=body, headers=operator)

    assert response.status_code == 201, response.text
    zone = response.json()
    assert response.headers["location"] == f"/v1/zones/{zone['id']}"
    assert zone["geometry"] == {"type": "MultiPolygon", "coordinates": [[SQUARE]]}
    assert (zone["name"], zone["risk_level"], zone["is_active"]) == (body["name"], "high", True)
    assert (await client.get(f"/v1/zones/{zone['id']}", headers=operator)).json() == zone

    audit = await owner.fetchrow(
        "SELECT organization_id, actor_id, action, before, after FROM core.audit_log "
        "WHERE entity_type = 'risk_zone' AND entity_id = $1",
        UUID(zone["id"]),
    )
    assert audit is not None
    assert (audit["organization_id"], audit["actor_id"], audit["action"]) == (
        data.RIMAC.id,
        SUB_RIMAC_OPERATOR,
        "create",
    )
    assert audit["before"] is None
    assert '"Quebrada Quirio"' in audit["after"]


@pytest.mark.parametrize(
    ("ring", "reason"),
    [
        pytest.param(BOW_TIE, "Self-intersection", id="corbata"),
        pytest.param(SQUARE[:-1], "no está cerrado", id="anillo-abierto"),
        pytest.param([[0, 0], [1, 0], [2, 0], [0, 0]], "", id="sin-area"),
        pytest.param(
            [[35.6, 139.6], [35.7, 139.6], [35.7, 139.8], [35.6, 139.6]],
            "rango",
            id="fuera-de-rango",
        ),
    ],
)
async def test_invalid_polygons_get_422_with_the_reason_and_nothing_is_saved(
    client: httpx2.AsyncClient,
    operator: dict[str, str],
    owner: asyncpg.Connection,
    ring: list[list[float]],
    reason: str,
) -> None:
    body = _zone(ring)
    response = await client.post("/v1/zones", json=body, headers=operator)

    assert response.status_code == 422, response.text
    [error] = response.json()["detail"]
    assert error["loc"] == ["body", "geometry"]
    assert error["type"] == "invalid_geometry"
    assert reason in error["msg"]
    assert not await owner.fetchval(
        "SELECT count(*) FROM core.risk_zones WHERE name = $1", body["name"]
    )


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"risk_level": "extreme"}, id="nivel-desconocido"),
        pytest.param({"name": "  "}, id="nombre-vacío"),
        pytest.param({"population_estimate": -1}, id="población-negativa"),
        pytest.param({"organization_id": str(uuid4())}, id="campo-extra"),
    ],
)
async def test_invalid_attributes_get_422(
    client: httpx2.AsyncClient, operator: dict[str, str], overrides: dict[str, Any]
) -> None:
    response = await client.post("/v1/zones", json=_zone(**overrides), headers=operator)
    assert response.status_code == 422, response.text


async def test_viewer_can_read_but_not_manage(
    client: httpx2.AsyncClient, operator: dict[str, str], viewer: dict[str, str]
) -> None:
    zone = await _create(client, operator)
    assert (await client.get("/v1/zones", headers=viewer)).status_code == 200
    assert (await client.get(f"/v1/zones/{zone['id']}", headers=viewer)).status_code == 200

    assert (await client.post("/v1/zones", json=_zone(), headers=viewer)).status_code == 403
    put = await client.put(f"/v1/zones/{zone['id']}", json=_zone(), headers=viewer)
    assert put.status_code == 403
    assert (await client.delete(f"/v1/zones/{zone['id']}", headers=viewer)).status_code == 403


async def test_each_seed_organization_only_sees_and_touches_its_own_zones(
    client: httpx2.AsyncClient, viewer: dict[str, str], other_org_admin: dict[str, str]
) -> None:
    rimac_ids = {z["id"] for z in (await client.get("/v1/zones", headers=viewer)).json()}
    other_ids = {z["id"] for z in (await client.get("/v1/zones", headers=other_org_admin)).json()}

    assert {str(data.Z_CHOSICA), str(data.Z_CHACLACAYO)} <= rimac_ids
    assert str(data.Z_PRUEBA) in other_ids
    assert not rimac_ids & other_ids

    # Una zona de otra organización no existe para este usuario: 404, nunca 403.
    foreign = f"/v1/zones/{data.Z_CHOSICA}"
    assert (await client.get(foreign, headers=other_org_admin)).status_code == 404
    assert (await client.put(foreign, json=_zone(), headers=other_org_admin)).status_code == 404
    assert (await client.delete(foreign, headers=other_org_admin)).status_code == 404


async def test_put_replaces_attributes_and_geometry_and_audits_before_and_after(
    client: httpx2.AsyncClient, operator: dict[str, str], owner: asyncpg.Connection
) -> None:
    zone = await _create(client, operator)
    smaller = [
        [-76.68, -11.92],
        [-76.62, -11.92],
        [-76.62, -11.98],
        [-76.68, -11.98],
        [-76.68, -11.92],
    ]
    body = _zone(smaller, name=zone["name"], risk_level="critical")

    response = await client.put(f"/v1/zones/{zone['id']}", json=body, headers=operator)

    assert response.status_code == 200, response.text
    assert response.json()["risk_level"] == "critical"
    assert response.json()["geometry"]["coordinates"] == [[smaller]]
    actions = await owner.fetch(
        "SELECT action, before ->> 'risk_level' AS before, after ->> 'risk_level' AS after "
        "FROM core.audit_log WHERE entity_id = $1 ORDER BY id",
        UUID(zone["id"]),
    )
    assert [(a["action"], a["before"], a["after"]) for a in actions] == [
        ("create", None, "high"),
        ("update", "high", "critical"),
    ]


async def test_delete_deactivates_and_put_can_reactivate(
    client: httpx2.AsyncClient, operator: dict[str, str]
) -> None:
    zone = await _create(client, operator)
    url = f"/v1/zones/{zone['id']}"

    assert (await client.delete(url, headers=operator)).status_code == 204
    assert (await client.delete(url, headers=operator)).status_code == 204  # idempotente

    active = {z["id"] for z in (await client.get("/v1/zones", headers=operator)).json()}
    everything = (await client.get("/v1/zones?include_inactive=true", headers=operator)).json()
    assert zone["id"] not in active
    assert next(z for z in everything if z["id"] == zone["id"])["is_active"] is False
    assert (await client.get(url, headers=operator)).json()["is_active"] is False

    body = _zone(name=zone["name"], is_active=True)
    assert (await client.put(url, json=body, headers=operator)).json()["is_active"] is True
