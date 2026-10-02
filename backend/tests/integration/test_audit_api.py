"""VIG-38: the audit log API against the real app and Postgres: admin only, isolation,
filters, and pagination that neither repeats nor skips rows while new ones arrive."""

import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
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
    SUB_RIMAC_ADMIN,
    SUB_RIMAC_OPERATOR,
    SUB_RIMAC_RESPONDER,
    SUB_RIMAC_VIEWER,
    TokenFactory,
)
from willay.seed import data
from willay.shared.clock import SystemClock

pytestmark = pytest.mark.integration

URL = "/v1/audit"


@pytest.fixture
async def client(database: Database, tokens: TokenFactory) -> AsyncIterator[httpx2.AsyncClient]:
    async with api_client(database, tokens) as client:
        yield client


def _as(tokens: TokenFactory, sub: UUID, role: str, organization: Any = RIMAC) -> dict[str, str]:
    return bearer(tokens.issue(sub, organization=organization, roles=(role,)))


@pytest.fixture
def admin(tokens: TokenFactory) -> dict[str, str]:
    return _as(tokens, SUB_RIMAC_ADMIN, "admin")


async def _record(
    owner: asyncpg.Connection,
    entity_id: UUID,
    at: datetime,
    *,
    action: str = "update",
    actor_id: UUID | None = SUB_RIMAC_ADMIN,
    organization_id: UUID = data.RIMAC.id,
    entity_type: str = "rule",
) -> int:
    entry_id: int = await owner.fetchval(
        "INSERT INTO core.audit_log (organization_id, actor_id, entity_type, entity_id, action,"
        " before, after, at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id",
        organization_id, actor_id, entity_type, entity_id, action,
        json.dumps({"cooldown_s": 600}), json.dumps({"cooldown_s": 900}), at,
    )  # fmt: skip
    return entry_id


async def _ensure_user(client: httpx2.AsyncClient, headers: dict[str, str]) -> None:
    """The user row is created on the first authenticated request (JIT)."""
    assert (await client.get("/v1/me", headers=headers)).status_code == 200


@pytest.mark.parametrize(
    ("sub", "role", "expected"),
    [
        (SUB_RIMAC_VIEWER, "viewer", 403),
        (SUB_RIMAC_RESPONDER, "responder", 403),
        (SUB_RIMAC_OPERATOR, "operator", 403),
        (SUB_RIMAC_ADMIN, "admin", 200),
    ],
)
async def test_only_admin_sees_the_audit_log(
    client: httpx2.AsyncClient, tokens: TokenFactory, sub: UUID, role: str, expected: int
) -> None:
    headers = _as(tokens, sub, role)
    assert (await client.get(URL, headers=headers)).status_code == expected
    assert (await client.get(f"{URL}/authors", headers=headers)).status_code == expected


async def test_an_entry_carries_its_author_by_name_and_both_states(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, admin: dict[str, str]
) -> None:
    await _ensure_user(client, admin)
    entity = uuid4()
    entry_id = await _record(owner, entity, SystemClock().now())
    page = (await client.get(URL, params={"entity_id": str(entity)}, headers=admin)).json()
    [entry] = page["items"]
    assert entry["id"] == entry_id
    assert entry["actor"]["id"] == str(SUB_RIMAC_ADMIN)
    assert entry["actor"]["name"]  # the user's full name, from core.users
    assert (entry["entity_type"], entry["action"]) == ("rule", "update")
    assert (entry["before"], entry["after"]) == ({"cooldown_s": 600}, {"cooldown_s": 900})
    assert page["next_cursor"] is None

    authors = (await client.get(f"{URL}/authors", headers=admin)).json()
    assert str(SUB_RIMAC_ADMIN) in [a["id"] for a in authors]


async def test_the_contact_themselves_has_no_author(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, admin: dict[str, str]
) -> None:
    entity = uuid4()
    await _record(
        owner, entity, SystemClock().now(), action="telegram_linked", actor_id=None,
        entity_type="contact",
    )  # fmt: skip
    [entry] = (await client.get(URL, params={"entity_id": str(entity)}, headers=admin)).json()[
        "items"
    ]
    assert entry["actor"] is None


async def test_pages_neither_repeat_nor_skip_while_new_entries_arrive(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, admin: dict[str, str]
) -> None:
    entity = uuid4()
    now = SystemClock().now()
    # Two entries share an instant: the id breaks the tie.
    times = [now - timedelta(minutes=m) for m in (5, 4, 3, 3, 1)]
    ids = [await _record(owner, entity, at) for at in times]
    expected = [i for _, i in sorted(zip(times, ids, strict=True), reverse=True)]

    seen: list[int] = []
    params: dict[str, Any] = {"entity_id": str(entity), "limit": 2}
    first = (await client.get(URL, params=params, headers=admin)).json()
    seen += [e["id"] for e in first["items"]]
    await _record(owner, entity, now)  # newer than everything: it belongs before page 1
    cursor = first["next_cursor"]
    while cursor:
        page = (await client.get(URL, params=params | {"cursor": cursor}, headers=admin)).json()
        seen += [e["id"] for e in page["items"]]
        cursor = page["next_cursor"]
    assert seen == expected


async def test_filters_by_type_author_and_dates(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, admin: dict[str, str]
) -> None:
    entity = uuid4()
    now = SystemClock().now()
    old = await _record(owner, entity, now - timedelta(days=3))
    by_operator = await _record(
        owner, entity, now - timedelta(hours=1), actor_id=SUB_RIMAC_OPERATOR
    )
    as_station = await _record(owner, entity, now, entity_type="station")

    async def ids(**filters: Any) -> list[int]:
        params = {"entity_id": str(entity), **filters}
        response = await client.get(URL, params=params, headers=admin)
        assert response.status_code == 200, response.text
        return [e["id"] for e in response.json()["items"]]

    assert await ids(entity_type="station") == [as_station]
    assert await ids(actor_id=str(SUB_RIMAC_OPERATOR)) == [by_operator]
    since = (now - timedelta(days=1)).isoformat()
    assert await ids(since=since) == [as_station, by_operator]
    assert await ids(until=since) == [old]


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"cursor": "basura"}, "cursor"),
        ({"since": "2026-12-22T10:00:00Z", "until": "2026-12-22T09:00:00Z"}, "since"),
        ({"entity_type": "user"}, "entity_type"),
        ({"limit": 101}, "limit"),
    ],
)
async def test_invalid_queries_get_422_on_their_field(
    client: httpx2.AsyncClient, admin: dict[str, str], params: dict[str, Any], field: str
) -> None:
    response = await client.get(URL, params=params, headers=admin)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == field


async def test_another_organization_never_sees_these_entries(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, tokens: TokenFactory
) -> None:
    entity = uuid4()
    await _record(owner, entity, SystemClock().now())
    other = _as(tokens, SUB_ISOLATION_ADMIN, "admin", organization=ISOLATION)
    response = await client.get(URL, params={"entity_id": str(entity)}, headers=other)
    assert response.json() == {"items": [], "next_cursor": None}
    authors = (await client.get(f"{URL}/authors", headers=other)).json()
    assert str(SUB_RIMAC_ADMIN) not in [a["id"] for a in authors]
