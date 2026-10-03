"""VIG-30: the demo's clean slate and the progress it reads, against real Postgres. The full run
(about 8 minutes against the stack) is a manual check: `make demo`."""

import json
from collections.abc import AsyncIterator
from datetime import timedelta

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from uuid_utils.compat import uuid7

from tests.integration.conftest import Database
from tests.integration.factories import (
    T0,
    Graph,
    add_level,
    create_contact,
    create_graph,
    create_group,
    create_incident,
)
from willay.demo import progress, reset
from willay.shared.db import create_engine

pytestmark = pytest.mark.integration


@pytest.fixture
async def owner_engine(database: Database) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database.migrate_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def app_engine(database: Database) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


async def _operations(conn: asyncpg.Connection, graph: Graph, contact_id: object) -> None:
    """A reading, its queue row, a heartbeat and an incident with an event and an alert."""
    await conn.execute(
        "INSERT INTO ingest.readings (station_id, organization_id, measured_at, received_at,"
        " value, quality) VALUES ($1, $2, $3, $3, 85.0, 'ok')",
        graph.station_id, graph.organization_id, T0,
    )  # fmt: skip
    await conn.execute(
        "INSERT INTO ingest.evaluation_queue (station_id, measured_at, organization_id,"
        " enqueued_at, available_at) VALUES ($1, $2, $3, $2, $2)",
        graph.station_id, T0, graph.organization_id,
    )  # fmt: skip
    await conn.execute(
        "INSERT INTO ingest.station_heartbeats (station_id, last_seen_at, last_measured_at,"
        " last_value, updated_at) VALUES ($1, $2, $2, 85.0, $2)",
        graph.station_id, T0,
    )  # fmt: skip
    incident_id = await create_incident(conn, graph)
    await conn.execute(
        "INSERT INTO core.incident_events (incident_id, organization_id, occurred_at,"
        " event_type, actor_type, payload) VALUES ($1, $2, $3, 'opened', 'system', '{}')",
        incident_id, graph.organization_id, T0,
    )  # fmt: skip
    await conn.execute(
        "INSERT INTO core.alerts (id, incident_id, level_order, contact_id, channel,"
        " destination, status) VALUES ($1, $2, 1, $3, 'email', 'a@b.test', 'pending')",
        uuid7(), incident_id, contact_id,
    )  # fmt: skip


async def _counts(conn: asyncpg.Connection, graph: Graph) -> dict[str, int]:
    org, station = graph.organization_id, graph.station_id
    queries = {
        "readings": ("SELECT count(*) FROM ingest.readings WHERE station_id = $1", station),
        "queue": ("SELECT count(*) FROM ingest.evaluation_queue WHERE station_id = $1", station),
        "heartbeats": (
            "SELECT count(*) FROM ingest.station_heartbeats WHERE station_id = $1",
            station,
        ),
        "incidents": ("SELECT count(*) FROM core.incidents WHERE organization_id = $1", org),
        "events": ("SELECT count(*) FROM core.incident_events WHERE organization_id = $1", org),
        "alerts": (
            "SELECT count(*) FROM core.alerts a JOIN core.incidents i ON i.id = a.incident_id"
            " WHERE i.organization_id = $1",
            org,
        ),
    }
    return {name: await conn.fetchval(sql, arg) for name, (sql, arg) in queries.items()}


async def test_clearing_deletes_the_operations_and_keeps_the_configuration(
    owner: asyncpg.Connection, owner_engine: AsyncEngine
) -> None:
    demo, other = await create_graph(owner), await create_graph(owner)
    rosa = await create_contact(owner, demo, "Rosa", telegram_chat_id=123)
    await _operations(owner, demo, rosa)
    await _operations(owner, other, await create_contact(owner, other, "Otra"))

    async with owner_engine.begin() as conn:
        cleared = await reset.clear(conn, demo.organization_id)

    assert (cleared.incidents, cleared.readings) == (1, 1)
    assert set((await _counts(owner, demo)).values()) == {0}
    assert set((await _counts(owner, other)).values()) == {1}  # another organization: intact
    configuration = await owner.fetchrow(
        "SELECT (SELECT count(*) FROM core.stations WHERE id = $1) AS stations,"
        " (SELECT count(*) FROM core.rules WHERE id = $2) AS rules,"
        " (SELECT telegram_chat_id FROM core.contacts WHERE id = $3) AS chat",
        demo.station_id, demo.rule_id, rosa,
    )  # fmt: skip
    assert configuration is not None
    assert dict(configuration) == {"stations": 1, "rules": 1, "chat": 123}


async def test_parking_forgets_the_heartbeats_only(
    owner: asyncpg.Connection, owner_engine: AsyncEngine
) -> None:
    demo = await create_graph(owner)
    await _operations(owner, demo, await create_contact(owner, demo, "Rosa"))

    async with owner_engine.begin() as conn:
        await reset.park(conn, demo.organization_id)

    counts = await _counts(owner, demo)
    assert counts.pop("heartbeats") == 0  # never reported: the silence worker ignores it
    assert set(counts.values()) == {1}


async def test_readiness_names_who_can_acknowledge_from_telegram_at_level_2(
    owner: asyncpg.Connection, app_engine: AsyncEngine
) -> None:
    graph = await create_graph(owner)
    linked = await create_contact(owner, graph, "Rosa", telegram_chat_id=123)
    unlinked = await create_contact(owner, graph, "Lucho")
    first = await create_group(owner, graph, await create_contact(owner, graph, "Óscar"))
    brigade = await create_group(owner, graph, linked, unlinked)
    await add_level(owner, graph, 1, (first, "email"), wait_s=120)
    await add_level(owner, graph, 2, (brigade, "telegram"), (brigade, "email"), wait_s=180)

    async with app_engine.connect() as conn:
        ready = await progress.readiness(conn, [graph.rule_id], 2)

    assert [(r.id, r.active, r.station_code) for r in ready.rules] == [
        (graph.rule_id, True, "EST-1")
    ]
    assert ready.levels == [(1, 120), (2, 180)]
    assert ready.telegram_at_ack_level == ["Rosa"]


async def test_events_carry_the_names_and_the_channel_an_acknowledgement_used(
    owner: asyncpg.Connection, app_engine: AsyncEngine
) -> None:
    graph = await create_graph(owner)
    rosa = await create_contact(owner, graph, "Rosa Brigada", telegram_chat_id=123)
    incident_id = await create_incident(owner, graph)
    await owner.execute(
        "INSERT INTO core.alerts (id, incident_id, level_order, contact_id, channel,"
        " destination, status, acknowledged_at) VALUES ($1, $2, 2, $3, 'telegram', '123',"
        " 'acknowledged', $4)",
        uuid7(), incident_id, rosa, T0 + timedelta(minutes=3),
    )  # fmt: skip
    for minutes, event_type, actor_type, actor_id, payload in [
        (2, "alert_sent", "system", None, {"contact_id": str(rosa), "channel": "telegram",
                                           "level_order": 2}),
        (3, "acknowledged", "contact", rosa, {}),
    ]:  # fmt: skip
        await owner.execute(
            "INSERT INTO core.incident_events (incident_id, organization_id, occurred_at,"
            " event_type, actor_type, actor_id, payload) VALUES ($1, $2, $3, $4, $5, $6, $7)",
            incident_id, graph.organization_id, T0 + timedelta(minutes=minutes), event_type,
            actor_type, actor_id, json.dumps(payload),
        )  # fmt: skip
    await owner.execute(
        "UPDATE core.incidents SET status = 'acknowledged', current_level = 2,"
        " acknowledged_at = $2, acknowledged_by_contact_id = $3 WHERE id = $1",
        incident_id, T0 + timedelta(minutes=3), rosa,
    )  # fmt: skip

    async with app_engine.connect() as conn:
        events = await progress.events(conn, graph.organization_id, T0)
        states = await progress.incidents(conn, graph.organization_id, [graph.rule_id], T0)

    sent, acknowledged = events
    assert (sent.contact_name, sent.station_code, sent.payload["level_order"]) == (
        "Rosa Brigada", "EST-1", 2
    )  # fmt: skip
    assert (acknowledged.actor_name, acknowledged.acknowledged_channel) == (
        "Rosa Brigada", "telegram"
    )  # fmt: skip
    state = states[graph.rule_id]
    assert (state.status, state.current_level, state.acknowledged) == ("acknowledged", 2, True)
    async with app_engine.connect() as conn:  # an incident opened before the run is not its own
        later = await progress.incidents(
            conn, graph.organization_id, [graph.rule_id], T0 + timedelta(seconds=1)
        )
    assert later == {}
