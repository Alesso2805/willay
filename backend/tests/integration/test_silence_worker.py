"""VIG-17: the silence worker against real Postgres, with time driven by FakeClock."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import Database
from tests.integration.evaluation import incidents, opened_payload
from tests.integration.factories import Graph, add_station, create_graph, create_rule, link_station
from willay.alerts.application.planning import AlertPlanner
from willay.alerts.infrastructure.sql_alerts import SqlAlertRepository
from willay.incidents.infrastructure.sql_incidents import SqlIncidentStore
from willay.rules.application.silence_check import SilenceChecker
from willay.rules.infrastructure.sql_silence import SqlSilenceRepository
from willay.shared.clock import FakeClock
from willay.shared.config import Settings
from willay.shared.db import create_engine
from willay.workers.silence import INTERVAL_S, run_silence

pytestmark = pytest.mark.integration

LAST_SEEN = datetime(2026, 11, 9, 8, 50, tzinfo=UTC)
# Factory stations: 10 s interval and the default K = 3.
THRESHOLD = timedelta(seconds=30)


@pytest.fixture
async def engine(database: Database) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


def _checker(engine: AsyncEngine, clock: FakeClock) -> SilenceChecker:
    return SilenceChecker(
        SqlSilenceRepository(),
        SqlIncidentStore(),
        clock,
        engine.begin,
        alerts=AlertPlanner(SqlAlertRepository()),
    )


async def _heartbeat(owner: asyncpg.Connection, station_id: object, value: float = 84.2) -> None:
    await owner.execute(
        "INSERT INTO ingest.station_heartbeats (station_id, last_seen_at, last_measured_at,"
        " last_value, updated_at) VALUES ($1, $2, $3, $4, $2)",
        station_id, LAST_SEEN, LAST_SEEN - timedelta(seconds=2), value,
    )  # fmt: skip


async def _report_again(owner: asyncpg.Connection, station_id: object, at: datetime) -> None:
    await owner.execute(
        "UPDATE ingest.station_heartbeats SET last_seen_at = $2, updated_at = $2"
        " WHERE station_id = $1",
        station_id,
        at,
    )


async def _recovered_events(owner: asyncpg.Connection, incident_id: object) -> list[asyncpg.Record]:
    return await owner.fetch(
        "SELECT payload FROM core.incident_events"
        " WHERE incident_id = $1 AND event_type = 'station_recovered'",
        incident_id,
    )


async def _watched_station(owner: asyncpg.Connection) -> Graph:
    """A station with a zone and a heartbeat, watched by the silence rule of create_graph."""
    graph = await create_graph(owner)
    await link_station(owner, graph)
    await _heartbeat(owner, graph.station_id)
    return graph


async def test_the_incident_opens_before_k_times_the_interval_plus_30_s(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    graph = await _watched_station(owner)
    # Cycles every 15 s, starting at an arbitrary phase relative to the last heartbeat.
    clock = FakeClock(LAST_SEEN + timedelta(seconds=7))
    checker = _checker(engine, clock)
    while not await incidents(owner, graph):
        assert clock.now() - LAST_SEEN <= THRESHOLD + timedelta(seconds=INTERVAL_S)
        await checker.run()
        clock.advance(timedelta(seconds=INTERVAL_S))

    [incident] = await incidents(owner, graph)
    opened_at = await owner.fetchval(
        "SELECT opened_at FROM core.incidents WHERE id = $1", incident["id"]
    )
    assert THRESHOLD <= opened_at - LAST_SEEN < THRESHOLD + timedelta(seconds=30)  # SPEC
    assert incident["dedup_key"] == f"{graph.rule_id}:{graph.zone_id}:{graph.station_id}"
    assert (incident["status"], incident["severity"], incident["trigger_value"]) == (
        "open",
        "critical",
        84.2,
    )

    payload = await opened_payload(owner, incident["id"])
    assert payload["rule_type"] == "silence"
    assert [r["value"] for r in payload["readings"]] == [84.2]  # the last known reading
    assert payload["details"] == {
        "last_seen_at": LAST_SEEN.isoformat(),
        "expected_interval_s": 10,
        "silence_multiplier": 3,
    }


async def test_later_cycles_do_not_open_a_second_incident(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    graph = await _watched_station(owner)
    clock = FakeClock(LAST_SEEN + THRESHOLD)
    checker = _checker(engine, clock)
    for _ in range(3):
        await checker.run()
        clock.advance(timedelta(seconds=INTERVAL_S))
    assert len(await incidents(owner, graph)) == 1


async def test_a_resolved_silence_does_not_reopen_until_its_cooldown_ends(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    graph = await _watched_station(owner)  # create_graph's rule has a 600 s cooldown
    clock = FakeClock(LAST_SEEN + THRESHOLD)
    checker = _checker(engine, clock)
    await checker.run()
    [incident] = await incidents(owner, graph)
    await owner.execute(
        "UPDATE core.incidents SET status = 'resolved', resolved_at = $2,"
        " resolution = 'false_alarm' WHERE id = $1",
        incident["id"],
        clock.now(),
    )

    clock.advance(timedelta(seconds=599))  # the station is still silent
    await checker.run()
    assert len(await incidents(owner, graph)) == 1

    clock.advance(timedelta(seconds=2))
    await checker.run()
    assert [i["status"] for i in await incidents(owner, graph)] == ["resolved", "open"]


async def test_a_zone_wide_rule_opens_one_incident_per_silent_station(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    graph = await _watched_station(owner)
    await owner.execute("UPDATE core.rules SET is_active = false WHERE id = $1", graph.rule_id)
    zone_rule = await create_rule(owner, graph, "silence", {})  # null station_id: the whole zone
    second = await add_station(owner, graph, "EST-2")
    await _heartbeat(owner, second)

    await _checker(engine, FakeClock(LAST_SEEN + THRESHOLD)).run()

    opened = await incidents(owner, graph)
    assert {i["station_id"] for i in opened} == {graph.station_id, second}
    assert {i["rule_id"] for i in opened} == {zone_rule}


@pytest.mark.parametrize(
    "setup",
    [
        pytest.param("DELETE FROM core.zone_stations WHERE station_id = $1", id="no-zone"),
        pytest.param(
            "DELETE FROM ingest.station_heartbeats WHERE station_id = $1", id="never-reported"
        ),
        pytest.param(
            "UPDATE core.stations SET status = 'inactive' WHERE id = $1", id="inactive-station"
        ),
        pytest.param(
            "UPDATE core.rules SET is_active = false WHERE station_id = $1", id="inactive-rule"
        ),
        pytest.param(
            "UPDATE core.risk_zones SET is_active = false "
            "WHERE id = (SELECT zone_id FROM core.rules WHERE station_id = $1)",
            id="inactive-zone",
        ),
    ],
)
async def test_stations_that_cannot_alert_are_ignored(
    engine: AsyncEngine, owner: asyncpg.Connection, setup: str
) -> None:
    graph = await _watched_station(owner)
    await owner.execute(setup, graph.station_id)
    await _checker(engine, FakeClock(LAST_SEEN + timedelta(hours=1))).run()
    assert await incidents(owner, graph) == []


async def test_a_station_that_reports_again_gets_station_recovered_once(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    graph = await _watched_station(owner)
    clock = FakeClock(LAST_SEEN + THRESHOLD)
    checker = _checker(engine, clock)
    await checker.run()
    [incident] = await incidents(owner, graph)

    await checker.run()
    assert await _recovered_events(owner, incident["id"]) == []  # still silent

    back = LAST_SEEN + timedelta(minutes=2)
    await _report_again(owner, graph.station_id, back)
    clock.set(back + timedelta(seconds=5))
    for _ in range(3):
        await checker.run()

    [event] = await _recovered_events(owner, incident["id"])
    assert json.loads(event["payload"])["last_seen_at"] == back.isoformat()
    [incident] = await incidents(owner, graph)
    assert incident["status"] == "open"  # no automatic closing: the operator resolves it


async def test_two_workers_record_a_recovery_only_once(
    engine: AsyncEngine, owner: asyncpg.Connection
) -> None:
    graph = await _watched_station(owner)
    await _checker(engine, FakeClock(LAST_SEEN + THRESHOLD)).run()
    [incident] = await incidents(owner, graph)
    await _report_again(owner, graph.station_id, LAST_SEEN + timedelta(minutes=2))

    # Both workers saw the recovery before either of them recorded it.
    async with engine.begin() as tx:
        [recovery] = [
            r
            for r in await SqlSilenceRepository().recoveries(tx)
            if r.incident_id == incident["id"]
        ]
    store, now = SqlIncidentStore(), LAST_SEEN + timedelta(minutes=3)
    recorded = []
    for _ in range(2):
        async with engine.begin() as tx:
            recorded.append(await store.record_recovery(tx, recovery, now))

    assert recorded == [True, False]  # the unique index from migration 0005
    assert len(await _recovered_events(owner, incident["id"])) == 1


async def test_the_worker_process_opens_the_incident_and_purges_old_windows(
    database: Database, owner: asyncpg.Connection, tmp_path: Path
) -> None:
    graph = await _watched_station(owner)
    now = LAST_SEEN + THRESHOLD
    old, recent = now - timedelta(hours=2), now - timedelta(minutes=10)
    for window in (old, recent):
        await owner.execute(
            "INSERT INTO ingest.rate_limit_windows (station_id, window_start, request_count)"
            " VALUES ($1, $2, 1)",
            graph.station_id,
            window,
        )

    async def windows() -> list[datetime]:
        rows = await owner.fetch(
            "SELECT window_start FROM ingest.rate_limit_windows WHERE station_id = $1"
            " ORDER BY window_start",
            graph.station_id,
        )
        return [r["window_start"] for r in rows]

    settings = Settings(database_url=database.app_url, heartbeat_dir=tmp_path)
    stop = asyncio.Event()
    worker = asyncio.create_task(run_silence(settings, stop, clock=FakeClock(now), interval_s=0.05))
    try:
        deadline = asyncio.get_running_loop().time() + 10
        while not await incidents(owner, graph) or len(await windows()) > 1:
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("the worker did not open the incident and purge in time")
            await asyncio.sleep(0.05)
    finally:
        stop.set()
        await worker
    assert await windows() == [recent]  # only windows older than one hour are purged
    assert (tmp_path / "silence.alive").exists()  # healthcheck heartbeat
