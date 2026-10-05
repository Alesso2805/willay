"""Structure of the initial migration: hypertable, constraints and reversibility."""

from datetime import timedelta

import asyncpg
import pytest

from tests.integration.conftest import Database, head_revision, migrate
from tests.integration.factories import T0, create_graph, create_incident

pytestmark = pytest.mark.integration


async def test_all_tables_exist(owner: asyncpg.Connection) -> None:
    rows = await owner.fetch(
        """
        SELECT table_schema, count(*) AS n FROM information_schema.tables
        WHERE table_schema IN ('core', 'ingest') AND table_name NOT LIKE 'future_%'
        GROUP BY table_schema
        """
    )
    # As SPEC says: core has 17 tables since VIG-43 (demo_runs).
    assert {r["table_schema"]: r["n"] for r in rows} == {"core": 17, "ingest": 4}


async def test_readings_is_a_hypertable_with_columnstore_and_retention(
    owner: asyncpg.Connection,
) -> None:
    interval = await owner.fetchval(
        """
        SELECT time_interval FROM timescaledb_information.dimensions
        WHERE hypertable_schema = 'ingest' AND hypertable_name = 'readings'
          AND column_name = 'measured_at'
        """
    )
    assert interval == timedelta(days=1)

    jobs = await owner.fetch(
        """
        SELECT proc_name, config FROM timescaledb_information.jobs
        WHERE hypertable_schema = 'ingest' AND hypertable_name = 'readings'
        """
    )
    configs = {j["proc_name"]: j["config"] for j in jobs}
    assert '"compress_after": "7 days"' in configs["policy_compression"]
    assert '"drop_after": "180 days"' in configs["policy_retention"]


async def test_app_can_write_readings_and_mark_them_evaluated(
    owner: asyncpg.Connection, app: asyncpg.Connection
) -> None:
    # Hypertable chunks inherit the parent table's privileges.
    graph = await create_graph(owner)
    await app.execute(
        """
        INSERT INTO ingest.readings (station_id, organization_id, measured_at, received_at,
                                     value, quality)
        VALUES ($1, $2, $3, $3, 12.5, 'ok')
        """,
        graph.station_id,
        graph.organization_id,
        T0,
    )
    await app.execute(
        "UPDATE ingest.readings SET evaluated_at = $1 WHERE station_id = $2",
        T0 + timedelta(seconds=2),
        graph.station_id,
    )
    # The same (station_id, measured_at) again hits the PK: the basis of "duplicate ignored".
    with pytest.raises(asyncpg.UniqueViolationError):
        await app.execute(
            """
            INSERT INTO ingest.readings (station_id, organization_id, measured_at,
                                         received_at, value, quality)
            VALUES ($1, $2, $3, $3, 99, 'ok')
            """,
            graph.station_id,
            graph.organization_id,
            T0,
        )


async def test_acknowledged_incident_requires_exactly_one_actor(
    owner: asyncpg.Connection,
) -> None:
    graph = await create_graph(owner)
    incident_id = await create_incident(owner, graph)

    with pytest.raises(asyncpg.CheckViolationError, match="incidents_acknowledged_by_check"):
        await owner.execute(
            "UPDATE core.incidents SET status = 'acknowledged', acknowledged_at = $2 WHERE id = $1",
            incident_id,
            T0,
        )


async def test_open_incident_cannot_have_an_acknowledging_actor(
    owner: asyncpg.Connection,
) -> None:
    graph = await create_graph(owner)
    incident_id = await create_incident(owner, graph)
    contact_id = await owner.fetchval(
        "INSERT INTO core.contacts (id, organization_id, full_name) "
        "VALUES (gen_random_uuid(), $1, 'Rosa') RETURNING id",
        graph.organization_id,
    )
    with pytest.raises(asyncpg.CheckViolationError, match="incidents_acknowledged_by_check"):
        await owner.execute(
            "UPDATE core.incidents SET acknowledged_by_contact_id = $2 WHERE id = $1",
            incident_id,
            contact_id,
        )


async def test_resolved_incident_requires_resolution(owner: asyncpg.Connection) -> None:
    graph = await create_graph(owner)
    incident_id = await create_incident(owner, graph)
    with pytest.raises(asyncpg.CheckViolationError, match="incidents_resolved_state_check"):
        await owner.execute(
            "UPDATE core.incidents SET status = 'resolved', resolved_at = $2 WHERE id = $1",
            incident_id,
            T0,
        )


async def test_only_one_active_incident_per_dedup_key(owner: asyncpg.Connection) -> None:
    graph = await create_graph(owner)
    first = await create_incident(owner, graph, dedup_key="k")

    with pytest.raises(asyncpg.UniqueViolationError, match="incidents_active_dedup_key"):
        await create_incident(owner, graph, dedup_key="k")

    # Once the first is resolved, the same cause can open another (the app enforces cooldown).
    await owner.execute(
        "UPDATE core.incidents SET status = 'resolved', resolved_at = $2, "
        "resolution = 'false_alarm' WHERE id = $1",
        first,
        T0,
    )
    await create_incident(owner, graph, dedup_key="k")


async def test_migrations_are_idempotent_and_reversible(
    database: Database, owner: asyncpg.Connection
) -> None:
    migrate(database)  # second run: no-op
    assert await owner.fetchval("SELECT version_num FROM alembic_version") == head_revision()

    migrate(database, "downgrade", "base")
    assert not await owner.fetchval(
        "SELECT count(*) FROM pg_namespace WHERE nspname IN ('core', 'ingest')"
    )

    migrate(database)
    assert await owner.fetchval("SELECT version_num FROM alembic_version") == head_revision()
