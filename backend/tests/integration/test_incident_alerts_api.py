"""VIG-26: an incident's alerts by recipient, with the email only for operator and admin and a
Telegram chat never returned (serialization test per role), against the real app and Postgres.
"""

import json
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

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
    SUB_RIMAC_ADMIN,
    SUB_RIMAC_OPERATOR,
    SUB_RIMAC_RESPONDER,
    SUB_RIMAC_VIEWER,
    TokenFactory,
)
from willay.seed import data
from willay.shared.clock import SystemClock

pytestmark = pytest.mark.integration

RULE = data.RULES[0]
EMAIL = "brigada@rimac.willay.test"
CHAT_ID = "987654321"


@pytest.fixture
async def client(database: Database, tokens: TokenFactory) -> AsyncIterator[httpx2.AsyncClient]:
    async with api_client(database, tokens) as client:
        yield client


def _as(tokens: TokenFactory, sub: UUID, role: str, organization: Any = RIMAC) -> dict[str, str]:
    return bearer(tokens.issue(sub, organization=organization, roles=(role,)))


async def _incident_with_alerts(owner: asyncpg.Connection) -> str:
    """An incident whose level 1 emailed and messaged Rosa, and skipped Óscar's Telegram."""
    now = SystemClock().now() - timedelta(hours=1)
    incident_id = uuid7()
    await owner.execute(
        """
        INSERT INTO core.incidents (id, organization_id, zone_id, rule_id, station_id, severity,
                                    dedup_key, opened_at, level_started_at)
        VALUES ($1, $2, $3, $4, $5, 'critical', $6, $7, $7)
        """,
        incident_id, data.RIMAC.id, RULE.zone_id, RULE.id, RULE.station_id,
        f"test:{uuid4()}", now,
    )  # fmt: skip
    alerts = [
        (data.C_BRIGADE, "email", EMAIL, "sent"),
        (data.C_BRIGADE, "telegram", CHAT_ID, "sent"),
        (data.C_OPERATOR, "telegram", None, "skipped"),
    ]
    for contact_id, channel, destination, status in alerts:
        await owner.execute(
            """
            INSERT INTO core.alerts (id, incident_id, level_order, contact_id, channel,
                                     destination, status, attempts, sent_at)
            VALUES ($1, $2, 1, $3, $4, $5, $6, $7, $8)
            """,
            uuid7(), incident_id, contact_id, channel, destination, status,
            1 if status == "sent" else 0, now if status == "sent" else None,
        )  # fmt: skip
    await owner.execute(
        "INSERT INTO core.incident_events (incident_id, organization_id, occurred_at,"
        " event_type, actor_type, payload) VALUES ($1, $2, $3, 'alert_skipped', 'system', $4)",
        incident_id, data.RIMAC.id, now,
        json.dumps({"contact_id": str(data.C_OPERATOR), "channel": "telegram",
                    "level_order": 1, "reason_code": "no_telegram"}),
    )  # fmt: skip
    return str(incident_id)


@pytest.mark.parametrize(
    ("sub", "role", "sees_email"),
    [
        (SUB_RIMAC_VIEWER, "viewer", False),
        (SUB_RIMAC_RESPONDER, "responder", False),
        (SUB_RIMAC_OPERATOR, "operator", True),
        (SUB_RIMAC_ADMIN, "admin", True),
    ],
)
async def test_each_role_sees_the_alerts_and_only_operator_and_admin_the_email(
    client: httpx2.AsyncClient,
    owner: asyncpg.Connection,
    tokens: TokenFactory,
    sub: UUID,
    role: str,
    sees_email: bool,
) -> None:
    incident_id = await _incident_with_alerts(owner)
    response = await client.get(
        f"/v1/incidents/{incident_id}/alerts", headers=_as(tokens, sub, role)
    )

    assert response.status_code == 200, response.text
    alerts = response.json()
    assert [(a["contact_name"], a["channel"], a["status"]) for a in alerts] == [
        ("Rosa Brigada", "email", "sent"),
        ("Rosa Brigada", "telegram", "sent"),
        ("Óscar Operador", "telegram", "skipped"),
    ]
    assert alerts[0]["email"] == (EMAIL if sees_email else None)
    # A code the dashboard says in words; the old Spanish text only for events before VIG-40.
    assert (alerts[2]["skipped_reason_code"], alerts[2]["skipped_reason"]) == ("no_telegram", None)
    # Whoever asks: no Telegram chat and no raw destination field at all.
    assert CHAT_ID not in response.text
    assert all("destination" not in a for a in alerts)
    assert all(a["email"] is None for a in alerts[1:])


async def test_another_organization_or_an_unknown_incident_gets_404(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, tokens: TokenFactory
) -> None:
    incident_id = await _incident_with_alerts(owner)
    other = _as(tokens, SUB_ISOLATION_ADMIN, "admin", organization=ISOLATION)
    assert (
        await client.get(f"/v1/incidents/{incident_id}/alerts", headers=other)
    ).status_code == 404
    operator = _as(tokens, SUB_RIMAC_OPERATOR, "operator")
    unknown = await client.get(f"/v1/incidents/{uuid7()}/alerts", headers=operator)
    assert unknown.status_code == 404


async def test_an_incident_without_alerts_gets_an_empty_list(
    client: httpx2.AsyncClient, owner: asyncpg.Connection, tokens: TokenFactory
) -> None:
    incident_id = await _incident_with_alerts(owner)
    await owner.execute("DELETE FROM core.alerts WHERE incident_id = $1", UUID(incident_id))
    operator = _as(tokens, SUB_RIMAC_OPERATOR, "operator")
    response = await client.get(f"/v1/incidents/{incident_id}/alerts", headers=operator)
    assert response.status_code == 200
    assert response.json() == []
