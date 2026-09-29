"""Worker evaluador (VIG-14): `python -m vigia.workers.evaluator`.

Toma lecturas de ingest.evaluation_queue y aplica las reglas de su estación. Despierta
con LISTEN vigia_evaluation_queue en cuanto la ingesta confirma un lote, y consulta cada
5 s por si un aviso se perdió. Varios procesos pueden correr a la vez: SKIP LOCKED
reparte las filas sin que dos tomen la misma.
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
        return result.claimed == batch_size  # lote lleno: probablemente quedan más

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
