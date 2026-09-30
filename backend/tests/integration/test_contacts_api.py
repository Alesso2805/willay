"""VIG-21: el enlace para vincular Telegram, contra la app y Postgres reales."""

import hashlib
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import UUID

import asyncpg
import httpx2
import pytest

from tests.integration.api import api_client, bearer
from tests.integration.conftest import Database
from tests.support.tokens import (
    AISLAMIENTO,
    RIMAC,
    SUB_AISLAMIENTO_ADMIN,
    SUB_RIMAC_ADMIN,
    SUB_RIMAC_OPERATOR,
    TokenFactory,
)
from vigia.seed import data
from vigia.shared.clock import SystemClock

pytestmark = pytest.mark.integration

BOT = "VigiaAlertasBot"
ROSA = data.C_BRIGADA  # Rosa Brigada, del seed (Rímac)


@pytest.fixture
async def client(database: Database, tokens: TokenFactory) -> AsyncIterator[httpx2.AsyncClient]:
    async with api_client(database, tokens, telegram_bot_username=BOT) as client:
        yield client


def _as(tokens: TokenFactory, sub: UUID, role: str, organization: Any = RIMAC) -> dict[str, str]:
    return bearer(tokens.issue(sub, organization=organization, roles=(role,)))


async def _link(client: httpx2.AsyncClient, headers: dict[str, str]) -> httpx2.Response:
    return await client.post(f"/v1/contacts/{ROSA}/telegram-link", headers=headers)


async def test_an_admin_gets_a_single_use_link_shown_once(
    client: httpx2.AsyncClient, tokens: TokenFactory, owner: asyncpg.Connection
) -> None:
    admin = _as(tokens, SUB_RIMAC_ADMIN, "admin")
    response = await _link(client, admin)

    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    url = response.json()["url"]
    prefix = f"https://t.me/{BOT}?start="
    assert url.startswith(prefix)
    token = url.removeprefix(prefix)
    assert len(token) == 43  # dentro de los 64 que admite Telegram en `start`

    row = await owner.fetchrow(
        "SELECT telegram_link_token_hash, telegram_link_expires_at FROM core.contacts"
        " WHERE id = $1",
        ROSA,
    )
    assert row is not None
    assert row["telegram_link_token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert row["telegram_link_expires_at"] - SystemClock().now() == pytest.approx(
        timedelta(days=7), abs=timedelta(minutes=1)
    )
    audit = await owner.fetchval(
        "SELECT after::text FROM core.audit_log WHERE entity_id = $1"
        " AND action = 'telegram_link_created' ORDER BY id DESC LIMIT 1",
        ROSA,
    )
    assert token not in audit

    # Otro enlace invalida el anterior: solo queda el hash del último.
    again = (await _link(client, admin)).json()["url"].removeprefix(prefix)
    stored = await owner.fetchval(
        "SELECT telegram_link_token_hash FROM core.contacts WHERE id = $1", ROSA
    )
    assert stored == hashlib.sha256(again.encode()).hexdigest() != row["telegram_link_token_hash"]


async def test_only_admins_of_the_organization_can_create_links(
    client: httpx2.AsyncClient, tokens: TokenFactory
) -> None:
    operator = _as(tokens, SUB_RIMAC_OPERATOR, "operator")
    other_admin = _as(tokens, SUB_AISLAMIENTO_ADMIN, "admin", organization=AISLAMIENTO)
    assert (await _link(client, operator)).status_code == 403
    assert (await _link(client, other_admin)).status_code == 404


async def test_without_a_bot_there_is_no_link(database: Database, tokens: TokenFactory) -> None:
    async with api_client(database, tokens) as client:  # sin VIGIA_TELEGRAM_BOT_USERNAME
        response = await _link(client, _as(tokens, SUB_RIMAC_ADMIN, "admin"))
    assert response.status_code == 503
