"""VIG-24: el worker escalation contra Postgres real, con el tiempo movido por FakeClock."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
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
from vigia.alerts.application.escalation import Escalator
from vigia.alerts.application.planning import AlertPlanner
from vigia.alerts.infrastructure.sql_alerts import SqlAlertRepository
from vigia.alerts.infrastructure.sql_escalation import SqlEscalationRepository
from vigia.shared.clock import FakeClock
from vigia.shared.config import Settings
from vigia.shared.db import create_engine
from vigia.workers.escalation import run_escalation

pytestmark = pytest.mark.integration

GT_35_ONCE = {"operator": "gt", "value": 3.5, "consecutive": 1}


@pytest.fixture
async def engine(database: Database, owner: asyncpg.Connection) -> AsyncIterator[AsyncEngine]:
    # Base compartida: el worker recorre todos los incidentes abiertos; los de otros tests
    # (casi todos con políticas sin niveles) no deben ocupar su cupo por ciclo.
    await owner.execute("DELETE FROM ingest.evaluation_queue")
    await owner.execute(
        "UPDATE core.incidents SET escalation_exhausted_at = opened_at"
        " WHERE status = 'open' AND escalation_exhausted_at IS NULL"
    )
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


class Case:
    def __init__(self, graph: Graph, incident_id: UUID, opened_at: datetime) -> None:
        self.graph, self.incident_id, self.opened_at = graph, incident_id, opened_at


async def _incident(
    engine: AsyncEngine, owner: asyncpg.Connection, *, level_one_reachable: bool = True
) -> Case:
    """Un incidente abierto con la política de la demo: 3 niveles de 120, 180 y 300 s."""
    graph = await create_graph(owner)
    await link_station(owner, graph)
    await create_rule(owner, graph, "threshold", GT_35_ONCE, station_id=graph.station_id)
    email = "ana@x.test" if level_one_reachable else None
    for level, (name, wait_s, address) in enumerate(
        [("Ana", 120, email), ("Beto", 180, "beto@x.test"), ("Caro", 300, "caro@x.test")],
        start=1,
    ):
        contact = await create_contact(owner, graph, name, email=address)
        group = await create_group(owner, graph, contact)
        await add_level(owner, graph, level, (group, "email"), wait_s=wait_s)
    station = Station(engine, graph)
    await station.send(3.6)
    [incident] = await incidents(owner, graph)
    opened_at = await owner.fetchval(
        "SELECT opened_at FROM core.incidents WHERE id = $1", incident["id"]
    )
    return Case(graph, incident["id"], opened_at)


def _escalator(engine: AsyncEngine, clock: FakeClock) -> Escalator:
    return Escalator(
        SqlEscalationRepository(), AlertPlanner(SqlAlertRepository()), clock, engine.begin
    )


async def _level(owner: asyncpg.Connection, case: Case) -> asyncpg.Record:
    row = await owner.fetchrow(
        "SELECT current_level, level_started_at, escalation_exhausted_at"
        " FROM core.incidents WHERE id = $1",
        case.incident_id,
    )
    assert row is not None
    return row


async def _escalations(owner: asyncpg.Connection, case: Case) -> list[tuple[str, dict[str, Any]]]:
    rows = await owner.fetch(
        "SELECT event_type, payload FROM core.incident_events WHERE incident_id = $1"
        " AND event_type IN ('escalated', 'escalation_exhausted') ORDER BY id",
        case.incident_id,
    )
    return [(r["event_type"], json.loads(r["payload"])) for r in rows]


async def _alerted(owner: asyncpg.Connection, case: Case) -> list[tuple[int, str]]:
    rows = await owner.fetch(
        "SELECT a.level_order, c.full_name FROM core.alerts a"
        " JOIN core.contacts c ON c.id = a.contact_id"
        " WHERE a.incident_id = $1 AND a.status <> 'skipped' ORDER BY a.level_order",
        case.incident_id,
    )
    return [(r["level_order"], r["full_name"]) for r in rows]


async def test_level_two_is_alerted_when_level_one_expires(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    case = await _incident(engine, owner)
    clock = FakeClock(case.opened_at + timedelta(seconds=119))
    escalator = _escalator(engine, clock)

    await escalator.run()
    assert (await _level(owner, case))["current_level"] == 1
    clock.advance(timedelta(seconds=1))
    await escalator.run()

    level = await _level(owner, case)
    assert (level["current_level"], level["level_started_at"]) == (2, clock.now())
    assert await _alerted(owner, case) == [(1, "Ana"), (2, "Beto")]
    assert await _escalations(owner, case) == [
        ("escalated", {"from_level": 1, "to_level": 2, "reason": "nadie confirmó en 120 s"})
    ]


async def test_acknowledging_stops_the_escalation(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    case = await _incident(engine, owner)
    await owner.execute(
        "UPDATE core.incidents SET status = 'acknowledged', acknowledged_at = now(),"
        " acknowledged_by_contact_id = (SELECT contact_id FROM core.alerts"
        " WHERE incident_id = $1 LIMIT 1) WHERE id = $1",
        case.incident_id,
    )
    await _escalator(engine, FakeClock(case.opened_at + timedelta(hours=1))).run()

    assert (await _level(owner, case))["current_level"] == 1
    assert await _escalations(owner, case) == []


async def test_the_policy_runs_out_after_its_last_level(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    case = await _incident(engine, owner)
    clock = FakeClock(case.opened_at)
    escalator = _escalator(engine, clock)
    for wait in (120, 180, 300):  # cada plazo cuenta desde que se avisó a ese nivel
        clock.advance(timedelta(seconds=wait))
        await escalator.run()

    level = await _level(owner, case)
    assert (level["current_level"], level["escalation_exhausted_at"]) == (3, clock.now())
    assert [event for event, _ in await _escalations(owner, case)] == [
        "escalated",
        "escalated",
        "escalation_exhausted",
    ]
    assert await _alerted(owner, case) == [(1, "Ana"), (2, "Beto"), (3, "Caro")]


async def test_a_first_level_that_reaches_nobody_escalates_at_once(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    case = await _incident(engine, owner, level_one_reachable=False)
    await _escalator(engine, FakeClock(case.opened_at + timedelta(seconds=1))).run()

    assert (await _level(owner, case))["current_level"] == 2
    [(_, payload)] = await _escalations(owner, case)
    assert payload["reason"] == "el nivel 1 no pudo avisar a nadie"


async def test_policy_changes_apply_to_incidents_in_progress(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    case = await _incident(engine, owner)
    clock = FakeClock(case.opened_at)
    escalator = _escalator(engine, clock)
    for wait in (120, 180):
        clock.advance(timedelta(seconds=wait))
        await escalator.run()  # queda en el nivel 3, el último

    # Un admin agrega un cuarto nivel mientras el incidente escala.
    dani = await create_contact(owner, case.graph, "Dani", email="dani@x.test")
    await add_level(owner, case.graph, 4, (await create_group(owner, case.graph, dani), "email"))
    clock.advance(timedelta(seconds=300))
    await escalator.run()

    level = await _level(owner, case)
    assert (level["current_level"], level["escalation_exhausted_at"]) == (4, None)


async def test_two_workers_escalate_an_incident_once(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    case = await _incident(engine, owner)
    clock = FakeClock(case.opened_at + timedelta(seconds=120))
    await asyncio.gather(_escalator(engine, clock).run(), _escalator(engine, clock).run())

    assert (await _level(owner, case))["current_level"] == 2
    assert len(await _escalations(owner, case)) == 1
    assert await _alerted(owner, case) == [(1, "Ana"), (2, "Beto")]


async def test_the_worker_process_escalates(
    engine: AsyncEngine, owner: asyncpg.Connection, database: Database, tmp_path: Path
) -> None:
    case = await _incident(engine, owner)
    settings = Settings(database_url=database.app_url, heartbeat_dir=tmp_path)
    stop = asyncio.Event()
    clock = FakeClock(case.opened_at + timedelta(seconds=120))
    worker = asyncio.create_task(run_escalation(settings, stop, clock=clock, interval_s=0.05))
    try:
        deadline = asyncio.get_running_loop().time() + 10
        while (await _level(owner, case))["current_level"] != 2:
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("el worker no escaló a tiempo")
            await asyncio.sleep(0.05)
    finally:
        stop.set()
        await worker
    assert (tmp_path / "escalation.alive").exists()
