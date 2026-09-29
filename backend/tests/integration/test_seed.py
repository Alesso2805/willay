"""Seed (VIG-04): conteos, idempotencia y API keys verificables."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import Database
from tests.integration.factories import FAST_HASHER
from vigia.seed import data
from vigia.seed.loader import IssuedKey, load_seed
from vigia.shared.clock import FakeClock
from vigia.shared.db import create_engine

pytestmark = pytest.mark.integration

SEED_ORGS = [org.id for org in data.ORGANIZATIONS]


@pytest.fixture
async def engine(database: Database) -> AsyncIterator[AsyncEngine]:
    # El seed corre como vigia_app, igual que en `make seed`.
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


async def _seed(engine: AsyncEngine, *, rotate_keys: bool = False) -> list[IssuedKey]:
    clock = FakeClock(datetime(2026, 10, 1, 8, 0, tzinfo=UTC))
    async with engine.begin() as conn:
        return await load_seed(conn, clock, FAST_HASHER, rotate_keys=rotate_keys)


async def _count(conn: asyncpg.Connection, sql: str) -> int:
    value = await conn.fetchval(sql, SEED_ORGS)
    assert isinstance(value, int)
    return value


async def _hashes(conn: asyncpg.Connection) -> dict[UUID, str]:
    rows = await conn.fetch(
        "SELECT id, api_key_hash FROM core.stations WHERE organization_id = ANY($1)", SEED_ORGS
    )
    return {r["id"]: r["api_key_hash"] for r in rows}


async def test_seed_creates_expected_data_and_is_idempotent(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    first = await _seed(engine)
    assert len(first) == 10
    hashes = await _hashes(owner)

    second = await _seed(engine)
    assert second == []  # nada nuevo: no se emiten ni cambian claves
    assert await _hashes(owner) == hashes

    in_orgs = "WHERE organization_id = ANY($1)"
    assert await _count(owner, "SELECT count(*) FROM core.organizations WHERE id = ANY($1)") == 2
    assert await _count(owner, f"SELECT count(*) FROM core.risk_zones {in_orgs}") == 3
    assert await _count(owner, f"SELECT count(*) FROM core.stations {in_orgs}") == 10
    assert await _count(owner, f"SELECT count(*) FROM core.rules {in_orgs}") == 6
    assert await _count(owner, f"SELECT count(*) FROM core.contacts {in_orgs}") == 5
    assert await _count(owner, f"SELECT count(*) FROM core.escalation_policies {in_orgs}") == 2
    rimac_levels = await owner.fetchval(
        "SELECT count(*) FROM core.escalation_levels WHERE policy_id = $1", data.P_RIMAC
    )
    assert rimac_levels == 3

    # La estación sin zona existe y no tiene filas en zone_stations.
    assert not await owner.fetchval(
        "SELECT count(*) FROM core.zone_stations WHERE station_id = $1", data.S_SIN_ZONA
    )
    # Los ids de Keycloak coinciden con el realm.
    kc_ids = await owner.fetch(
        "SELECT keycloak_org_id FROM core.organizations WHERE id = ANY($1)", SEED_ORGS
    )
    assert {r["keycloak_org_id"] for r in kc_ids} == {
        UUID("1d44f4b3-b1df-457f-b717-20926a20166e"),
        UUID("d32ffb77-666e-4986-8234-9f1db8437302"),
    }


async def test_issued_keys_verify_and_rotation_invalidates_old_ones(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    await _seed(engine)  # puede no emitir nada si otro test ya sembró
    before = await _seed(engine, rotate_keys=True)
    assert {k.station_code for k in before} == {s.code for s in data.STATIONS}

    hashes = await _hashes(owner)
    for key in before:
        assert FAST_HASHER.verify(hashes[key.station_id], key.api_key)

    after = await _seed(engine, rotate_keys=True)
    rotated = await _hashes(owner)
    for old, new in zip(before, after, strict=True):
        assert not FAST_HASHER.verify(rotated[old.station_id], old.api_key)
        assert FAST_HASHER.verify(rotated[new.station_id], new.api_key)
