"""VIG-11: the simulator sends real batches to the API and they are stored and enqueued."""

from datetime import timedelta

import asyncpg
import pytest

from tests.integration.api import api_client
from tests.integration.conftest import Database
from tests.integration.factories import create_station_with_key
from tests.support.tokens import TokenFactory
from vigia.ingestion.application.simulate import SimulatedStation, TickReport, run_simulation
from vigia.ingestion.domain.simulation import Behavior, StationPlan, value_at
from vigia.ingestion.infrastructure.http_sender import HttpReadingSender
from vigia.shared.clock import FakeClock, SystemClock

pytestmark = pytest.mark.integration


async def test_simulated_station_feeds_the_real_api(
    database: Database, tokens: TokenFactory, owner: asyncpg.Connection
) -> None:
    graph, key = await create_station_with_key(owner)
    # One clock shared by the simulator and the API: 10 s steps without really waiting.
    clock = FakeClock(SystemClock().now() - timedelta(minutes=2))
    plan = StationPlan("EST-1", "discharge", Behavior.SILENCE, event_step=4)

    async def sleep(seconds: float) -> None:
        clock.advance(timedelta(seconds=seconds))

    reports: list[TickReport] = []
    async with api_client(database, tokens, clock=clock) as client:
        await run_simulation(
            [SimulatedStation(plan, key)],
            seed=42,
            interval_s=10,
            steps=6,
            clock=clock,
            sleep=sleep,
            sender=HttpReadingSender(client),
            on_tick=reports.append,
        )

    assert [r.statuses.get("EST-1") for r in reports] == [202, 202, 202, 202, None, None]
    rows = await owner.fetch(
        "SELECT value FROM ingest.readings WHERE station_id = $1 ORDER BY measured_at",
        graph.station_id,
    )
    assert [r["value"] for r in rows] == [value_at(plan, 42, s) for s in range(4)]
    queued = await owner.fetchval(
        "SELECT count(*) FROM ingest.evaluation_queue WHERE station_id = $1", graph.station_id
    )
    assert queued == 4
