"""VIG-20 (part 1): opening an incident creates the alerts of its level 1."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import Database
from tests.integration.evaluation import Station, incidents
from tests.integration.factories import (
    Graph,
    add_level,
    create_contact,
    create_graph,
    create_group,
    create_rule,
    link_station,
)
from willay.alerts.application.planning import AlertPlanner
from willay.alerts.infrastructure.sql_alerts import SqlAlertRepository
from willay.incidents.infrastructure.sql_incidents import SqlIncidentStore
from willay.rules.application.silence_check import SilenceChecker
from willay.rules.infrastructure.sql_silence import SqlSilenceRepository
from willay.shared import notifications
from willay.shared.clock import FakeClock
from willay.shared.db import create_engine

pytestmark = pytest.mark.integration

GT_35_ONCE = {"operator": "gt", "value": 3.5, "consecutive": 1}


@pytest.fixture
async def engine(database: Database, owner: asyncpg.Connection) -> AsyncIterator[AsyncEngine]:
    await owner.execute("DELETE FROM ingest.evaluation_queue")  # shared database
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


class People:
    """Ana has email and Telegram; Beto has nothing; Caro has only email."""

    def __init__(self, ana: UUID, beto: UUID, caro: UUID) -> None:
        self.ana, self.beto, self.caro = ana, beto, caro


async def _policy(owner: asyncpg.Connection, graph: Graph) -> People:
    ana = await create_contact(owner, graph, "Ana", email="ana@x.test", telegram_chat_id=111)
    beto = await create_contact(owner, graph, "Beto")
    caro = await create_contact(owner, graph, "Caro", email="caro@x.test")
    operators = await create_group(owner, graph, ana, beto)
    field = await create_group(owner, graph, ana, caro)  # Ana is in both groups
    await add_level(owner, graph, 1, (operators, "email"), (field, "email"), (field, "telegram"))
    await add_level(owner, graph, 2, (operators, "email"))  # opening alerts only level 1
    return People(ana, beto, caro)


async def _station(engine: AsyncEngine, owner: asyncpg.Connection) -> tuple[Station, People]:
    graph = await create_graph(owner)
    await link_station(owner, graph)
    await create_rule(owner, graph, "threshold", GT_35_ONCE, station_id=graph.station_id)
    return Station(engine, graph), await _policy(owner, graph)


async def _alerts(owner: asyncpg.Connection, incident_id: UUID) -> set[tuple[object, ...]]:
    rows = await owner.fetch(
        "SELECT contact_id, channel, destination, status, level_order,"
        " next_attempt_at IS NOT NULL AS scheduled FROM core.alerts WHERE incident_id = $1",
        incident_id,
    )
    return {tuple(r.values()) for r in rows}


async def test_opening_creates_one_alert_per_contact_and_channel_of_level_one(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    station, people = await _station(engine, owner)
    await station.send(3.6)

    [incident] = await incidents(owner, station.graph)
    assert await _alerts(owner, incident["id"]) == {
        (people.ana, "email", "ana@x.test", "pending", 1, True),  # only one, though in 2 groups
        (people.caro, "email", "caro@x.test", "pending", 1, True),
        (people.ana, "telegram", "111", "pending", 1, True),
        (people.beto, "email", None, "skipped", 1, False),
        (people.caro, "telegram", None, "skipped", 1, False),
    }

    skipped = await owner.fetch(
        "SELECT payload FROM core.incident_events WHERE incident_id = $1"
        " AND event_type = 'alert_skipped' ORDER BY id",
        incident["id"],
    )
    reasons = {
        (p["contact_id"], p["channel"], p["reason_code"])
        for p in (json.loads(r["payload"]) for r in skipped)
    }
    assert reasons == {
        (str(people.beto), "email", "no_email"),
        (str(people.caro), "telegram", "no_telegram"),
    }
    # The destination is personal data: it stays out of the timeline.
    assert "@" not in " ".join(r["payload"] for r in skipped)


async def test_readings_that_worsen_the_incident_do_not_alert_again(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    station, _ = await _station(engine, owner)
    await station.send(3.6, 3.9, 4.2)
    [incident] = await incidents(owner, station.graph)
    assert len(await _alerts(owner, incident["id"])) == 5


async def test_the_dispatcher_is_woken_when_the_incident_commits(
    engine: AsyncEngine, owner: asyncpg.Connection, database: Database
) -> None:
    station, _ = await _station(engine, owner)
    listener = await asyncpg.connect(database.owner_dsn)
    woken = asyncio.Event()
    await listener.add_listener(notifications.ALERTS, lambda *_: woken.set())
    try:
        await station.send(3.6)
        await asyncio.wait_for(woken.wait(), timeout=5)
    finally:
        await listener.close()


async def test_an_alert_to_be_sent_always_has_a_destination(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    station, people = await _station(engine, owner)
    await station.send(3.6)
    [incident] = await incidents(owner, station.graph)
    with pytest.raises(asyncpg.CheckViolationError, match="alerts_destination_check"):
        await owner.execute(
            "INSERT INTO core.alerts (id, incident_id, level_order, contact_id, channel, status)"
            " VALUES (gen_random_uuid(), $1, 1, $2, 'email', 'pending')",
            incident["id"],
            people.beto,
        )


async def test_a_silence_incident_alerts_its_first_level_too(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    graph = await create_graph(owner)  # with its silence rule
    await link_station(owner, graph)
    last_seen = datetime(2026, 11, 20, 14, 0, tzinfo=UTC)
    await owner.execute(
        "INSERT INTO ingest.station_heartbeats (station_id, last_seen_at, last_measured_at,"
        " last_value, updated_at) VALUES ($1, $2, $2, 84.2, $2)",
        graph.station_id,
        last_seen,
    )
    people = await _policy(owner, graph)
    checker = SilenceChecker(
        SqlSilenceRepository(),
        SqlIncidentStore(),
        FakeClock(last_seen + timedelta(minutes=1)),
        engine.begin,
        alerts=AlertPlanner(SqlAlertRepository()),
    )
    await checker.run()

    [incident] = await incidents(owner, graph)
    pending = {(a[0], a[1]) for a in await _alerts(owner, incident["id"]) if a[3] == "pending"}
    assert pending == {(people.ana, "email"), (people.caro, "email"), (people.ana, "telegram")}
