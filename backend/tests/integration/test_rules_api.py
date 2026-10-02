"""VIG-27: rules CRUD against the real app and Postgres: permissions per role, validation per
type, audit, isolation, and the evaluator reading what the API stored."""

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import asyncpg
import httpx2
import pytest

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
from willay.rules.domain.threshold import parse_threshold
from willay.rules.infrastructure.sql_rules import SqlRuleRepository
from willay.seed import data
from willay.shared.db import create_engine

pytestmark = pytest.mark.integration

URL = "/v1/rules"


@pytest.fixture
async def client(database: Database, tokens: TokenFactory) -> AsyncIterator[httpx2.AsyncClient]:
    async with api_client(database, tokens) as client:
        yield client


def _as(tokens: TokenFactory, sub: UUID, role: str, organization: Any = RIMAC) -> dict[str, str]:
    return bearer(tokens.issue(sub, organization=organization, roles=(role,)))


@pytest.fixture
def operator(tokens: TokenFactory) -> dict[str, str]:
    return _as(tokens, SUB_RIMAC_OPERATOR, "operator")


def _threshold(**changes: Any) -> dict[str, Any]:
    """A rule on the Quirio ravine (Chosica), inactive so it never fires in other tests."""
    body: dict[str, Any] = {
        "type": "threshold",
        "zone_id": str(data.Z_CHOSICA),
        "station_id": str(data.S_QUIRIO),
        "params": {"operator": "ge", "value": 999, "consecutive": 2},
        "severity": "critical",
        "escalation_policy_id": str(data.P_RIMAC),
        "cooldown_s": 900,
        "is_active": False,
    }
    return body | changes


@pytest.mark.parametrize(
    ("sub", "role", "writes"),
    [
        (SUB_RIMAC_VIEWER, "viewer", 403),
        (SUB_RIMAC_RESPONDER, "responder", 403),
        (SUB_RIMAC_OPERATOR, "operator", 201),
        (SUB_RIMAC_ADMIN, "admin", 201),
    ],
)
async def test_everyone_reads_and_operator_and_admin_write(
    client: httpx2.AsyncClient, tokens: TokenFactory, sub: UUID, role: str, writes: int
) -> None:
    headers = _as(tokens, sub, role)
    assert (await client.get(URL, headers=headers)).status_code == 200
    assert (await client.post(URL, json=_threshold(), headers=headers)).status_code == writes


async def test_the_seed_rules_come_by_zone_with_their_station_and_policy(
    client: httpx2.AsyncClient, operator: dict[str, str]
) -> None:
    rules = (await client.get(URL, headers=operator)).json()
    zones = [r["zone"]["name"] for r in rules]
    assert zones == sorted(zones)
    drop = next(r for r in rules if r["id"] == str(data.RULES[0].id))
    assert drop["type"] == "rate_of_change"
    assert drop["station"]["unit"] == "m3/s"
    assert drop["params"] == {"direction": "down", "delta": 40.0, "window_minutes": 10}
    assert drop["escalation_policy"]["name"] == "Protocolo Rímac"
    zone_wide = [r for r in rules if r["station"] is None]
    assert {r["type"] for r in zone_wide} == {"silence"}
    assert "Zona de prueba" not in zones  # the other organization's


async def test_a_rule_is_created_edited_and_deactivated_with_its_audit(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, operator: dict[str, str]
) -> None:
    created = await client.post(
        URL,
        json=_threshold(params={"operator": "ge", "value": 999, "consecutive": 2}),
        headers=operator,
    )
    assert created.status_code == 201, created.text
    rule = created.json()
    assert rule["params"] == {"operator": "ge", "value": 999.0, "consecutive": 2}
    assert rule["station"]["code"] == "RIM-CHO-02"  # the Quirio ravine
    url = f"{URL}/{rule['id']}"

    edited = await client.put(
        url, json=_threshold(params={"operator": "ge", "value": 998.5, "consecutive": 4}),
        headers=operator,
    )  # fmt: skip
    assert edited.json()["params"]["value"] == 998.5
    assert (await client.delete(url, headers=operator)).status_code == 204
    assert (await client.get(url, headers=operator)).json()["is_active"] is False
    listed = (await client.get(URL, headers=operator)).json()
    assert rule["id"] not in [r["id"] for r in listed]
    every = (await client.get(URL, params={"include_inactive": True}, headers=operator)).json()
    assert rule["id"] in [r["id"] for r in every]

    rows = await owner.fetch(
        "SELECT action, actor_id, after FROM core.audit_log"
        " WHERE entity_type = 'rule' AND entity_id = $1 ORDER BY id",
        UUID(rule["id"]),
    )
    assert [r["action"] for r in rows] == ["create", "update"]  # it was already inactive
    assert {r["actor_id"] for r in rows} == {SUB_RIMAC_OPERATOR}
    assert json.loads(rows[1]["after"])["params"]["consecutive"] == 4
    created_by = await owner.fetchval(
        "SELECT created_by FROM core.rules WHERE id = $1", UUID(rule["id"])
    )
    assert created_by == SUB_RIMAC_OPERATOR


async def test_reactivating_and_deactivating_are_audited(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, operator: dict[str, str]
) -> None:
    rule = (await client.post(URL, json=_threshold(), headers=operator)).json()
    url = f"{URL}/{rule['id']}"
    # A huge value: it never fires even while active.
    active = await client.put(url, json=_threshold(is_active=True), headers=operator)
    assert active.json()["is_active"] is True
    await client.delete(url, headers=operator)
    actions = await owner.fetch(
        "SELECT action FROM core.audit_log WHERE entity_type = 'rule' AND entity_id = $1"
        " ORDER BY id",
        UUID(rule["id"]),
    )
    assert [r["action"] for r in actions] == ["create", "update", "deactivate"]


@pytest.mark.parametrize(
    ("body", "field"),
    [
        (_threshold(params={"operator": "ge", "value": 1, "consecutive": 61}), "consecutive"),
        (_threshold(params={"operator": "between", "value": 1, "consecutive": 1}), "operator"),
        (_threshold(station_id=None), "station_id"),  # a threshold compares in a station's unit
        (_threshold(station_id=str(data.S_HUACHIPA)), "station_id"),  # not a Chosica station
        (_threshold(zone_id=str(data.Z_TEST)), "zone_id"),  # another organization's
        (_threshold(escalation_policy_id=str(data.P_ISOLATION)), "escalation_policy_id"),
        (_threshold(cooldown_s=-1), "cooldown_s"),
        ({**_threshold(type="silence"), "params": {"multiplier": 5}}, "multiplier"),
    ],
)
async def test_an_invalid_rule_gets_422_on_its_field(
    client: httpx2.AsyncClient, operator: dict[str, str], body: dict[str, Any], field: str
) -> None:
    response = await client.post(URL, json=body, headers=operator)
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"][-1] == field


async def test_the_type_of_a_rule_never_changes(
    client: httpx2.AsyncClient, operator: dict[str, str]
) -> None:
    rule = (await client.post(URL, json=_threshold(), headers=operator)).json()
    silence = {**_threshold(type="silence"), "params": {}}
    response = await client.put(f"{URL}/{rule['id']}", json=silence, headers=operator)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "type"]


async def test_the_evaluator_reads_a_rule_the_api_stored(
    client: httpx2.AsyncClient, database: Database, operator: dict[str, str]
) -> None:
    rule = (await client.post(URL, json=_threshold(is_active=True), headers=operator)).json()
    engine = create_engine(database.app_url)
    try:
        async with engine.begin() as tx:
            applicable = await SqlRuleRepository().applicable(tx, data.RIMAC.id, data.S_QUIRIO)
    finally:
        await engine.dispose()
    mine = next(r for r in applicable if str(r.id) == rule["id"])
    assert parse_threshold(mine.params).consecutive == 2
    await client.delete(f"{URL}/{rule['id']}", headers=operator)


async def test_another_organization_never_sees_or_touches_these_rules(
    client: httpx2.AsyncClient, tokens: TokenFactory, operator: dict[str, str]
) -> None:
    rule = (await client.post(URL, json=_threshold(), headers=operator)).json()
    other = _as(tokens, SUB_ISOLATION_ADMIN, "admin", organization=ISOLATION)
    assert rule["id"] not in (await client.get(URL, headers=other)).text
    url = f"{URL}/{rule['id']}"
    assert (await client.get(url, headers=other)).status_code == 404
    mine = _threshold(
        zone_id=str(data.Z_TEST), station_id=str(data.S_AIS_1),
        escalation_policy_id=str(data.P_ISOLATION),
    )  # fmt: skip
    assert (await client.put(url, json=mine, headers=other)).status_code == 404
    assert (await client.delete(url, headers=other)).status_code == 404
