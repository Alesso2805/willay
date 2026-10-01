"""Evaluator worker (VIG-14): `python -m vigia.workers.evaluator`.

Takes readings from ingest.evaluation_queue and applies their station's rules. Wakes on
LISTEN vigia_evaluation_queue when ingestion commits a batch and polls every 5 s for lost
notifications. Several processes can run at once: SKIP LOCKED never hands out a row twice.
"""

import asyncio

from vigia.alerts.application.planning import AlertPlanner
from vigia.alerts.infrastructure.sql_alerts import SqlAlertRepository
from vigia.incidents.infrastructure.sql_incidents import SqlIncidentStore
from vigia.rules.application.evaluate import ReadingEvaluator, process_batch
from vigia.rules.application.rule_evaluator import RuleEvaluator
from vigia.rules.infrastructure.pg_queue import PostgresEvaluationQueue
from vigia.rules.infrastructure.sql_rules import SqlReadingHistory, SqlRuleRepository
from vigia.shared import notifications
from vigia.shared.clock import Clock, SystemClock
from vigia.shared.config import Settings
from vigia.shared.db import create_engine
from vigia.shared.pg_listen import asyncpg_dsn, listen
from vigia.workers._runner import run_async_worker, run_loop

NAME = "evaluator"
POLL_INTERVAL_S = 5.0
BATCH_SIZE = 20


async def run_evaluator(
    settings: Settings,
    stop: asyncio.Event,
    *,
    clock: Clock | None = None,
    evaluator: ReadingEvaluator | None = None,
    poll_interval_s: float = POLL_INTERVAL_S,
    batch_size: int = BATCH_SIZE,
) -> None:
    clock = clock or SystemClock()
    engine = create_engine(settings.database_url)
    queue = PostgresEvaluationQueue(engine, clock)
    rules = evaluator or RuleEvaluator(
        SqlRuleRepository(),
        SqlReadingHistory(),
        SqlIncidentStore(),
        clock,
        alerts=AlertPlanner(SqlAlertRepository()),
    )

    async def tick() -> bool:
        result = await process_batch(queue, rules, engine.begin, limit=batch_size)
        return result.claimed == batch_size  # full batch: more likely remain

    try:
        dsn = asyncpg_dsn(settings.database_url)
        async with listen(dsn, notifications.EVALUATION_QUEUE) as wakeup:
            heartbeat = settings.heartbeat_dir / f"{NAME}.alive"
            await run_loop(NAME, poll_interval_s, heartbeat, stop, tick, wakeup)
    finally:
        await engine.dispose()


def main() -> None:
    run_async_worker(NAME, run_evaluator)


if __name__ == "__main__":
    main()
