"""Helpers to test rules end to end: ingestion → queue → evaluator → incident."""

import json
from datetime import datetime, timedelta
from typing import Any

import asyncpg
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.factories import Graph
from vigia.alerts.application.planning import AlertPlanner
from vigia.alerts.infrastructure.sql_alerts import SqlAlertRepository
from vigia.incidents.infrastructure.sql_incidents import SqlIncidentStore
from vigia.ingestion.domain.readings import ClassifiedReading, Quality
from vigia.ingestion.infrastructure.repositories import SqlReadingWriter
from vigia.rules.application.evaluate import process_batch
from vigia.rules.application.rule_evaluator import RuleEvaluator
from vigia.rules.infrastructure.pg_queue import PostgresEvaluationQueue
from vigia.rules.infrastructure.sql_rules import SqlReadingHistory, SqlRuleRepository
from vigia.shared.clock import Clock, SystemClock


class Station:
    """A station that sends a reading every `interval_s` and an evaluator that processes
    them one by one, like the real worker."""

    def __init__(
        self,
        engine: AsyncEngine,
        graph: Graph,
        *,
        interval_s: float = 10,
        clock: Clock | None = None,
    ) -> None:
        self.engine, self.graph = engine, graph
        self.clock = clock or SystemClock()
        self.queue = PostgresEvaluationQueue(engine, self.clock)
        self.evaluator = RuleEvaluator(
            SqlRuleRepository(),
            SqlReadingHistory(),
            SqlIncidentStore(),
            self.clock,
            alerts=AlertPlanner(SqlAlertRepository()),
        )
        self.interval = timedelta(seconds=interval_s)
        self.start = self.clock.now() - timedelta(minutes=30)
        self.sent = 0

    async def send(self, *values: float) -> None:
        for value in values:
            await self._write(ClassifiedReading(self._next_time(), value, Quality.OK))
            await process_batch(self.queue, self.evaluator, self.engine.begin, limit=10)

    async def write_late(self, value: float) -> None:
        """An interleaved late reading (> 1 h): it is stored but not enqueued."""
        await self._write(ClassifiedReading(self._next_time(), value, Quality.LATE))

    def _next_time(self) -> datetime:
        self.sent += 1
        return self.start + self.interval * self.sent

    async def _write(self, reading: ClassifiedReading) -> None:
        async with self.engine.begin() as tx:
            await SqlReadingWriter(tx).store_and_enqueue(
                self.graph.station_id,
                self.graph.organization_id,
                [reading],
                self.clock.now(),
                reading if reading.quality is Quality.OK else None,
            )


async def incidents(owner: asyncpg.Connection, graph: Graph) -> list[asyncpg.Record]:
    return await owner.fetch(
        "SELECT id, rule_id, zone_id, station_id, severity, trigger_value, dedup_key, status "
        "FROM core.incidents WHERE organization_id = $1 ORDER BY opened_at",
        graph.organization_id,
    )


async def opened_payload(owner: asyncpg.Connection, incident_id: object) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(
        await owner.fetchval(
            "SELECT payload FROM core.incident_events WHERE incident_id = $1 "
            "AND event_type = 'opened'",
            incident_id,
        )
    )
    return payload
