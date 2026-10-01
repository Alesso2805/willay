# Reprocess readings that failed in the evaluator

A reading ends up with `failed_at` when the evaluator failed 5 times to evaluate it (ADR-0002). It leaves the queue so as not to block it, but **it was not evaluated**: if it triggered a rule, that alert did not go out. You have to review the cause and reprocess it.

## 1. See what failed and why

```bash
docker compose exec postgres psql -U postgres -d willay -c "
  SELECT q.id, s.code, q.measured_at, q.attempts, q.failed_at, q.last_error
  FROM ingest.evaluation_queue q JOIN core.stations s ON s.id = q.station_id
  WHERE q.failed_at IS NOT NULL
  ORDER BY q.failed_at DESC;"
```

`last_error` holds the exception from the last attempt. If it says `sin completar tras 5 intentos` ("not completed after 5 attempts"), the worker died during the last attempt (restarts, memory, deployments) and there was no rule error.

## 2. Fix the cause

- **Error in a rule** (e.g. inconsistent parameters): fix the rule from the dashboard or deploy the evaluator fix.
- **Database or network down** during the 5 attempts: reprocessing is enough.

Do not reprocess without fixing: it will fail 5 times again.

## 3. Return the rows to the queue

This resets the attempts and makes the rows available immediately. The evaluator picks them up on its next poll (≤ 5 s):

```bash
docker compose exec postgres psql -U postgres -d willay -c "
  UPDATE ingest.evaluation_queue
  SET failed_at = NULL, attempts = 0, available_at = now(),
      last_error = 'reprocesada a mano: ' || coalesce(last_error, '')
  WHERE failed_at IS NOT NULL
    AND id IN (/* ids from step 1 */);
  NOTIFY willay_evaluation_queue;"
```

`NOTIFY` wakes the evaluator without waiting for the periodic poll.

## 4. Verify

The row disappears from the queue and the reading has `evaluated_at`:

```bash
docker compose exec postgres psql -U postgres -d willay -c "
  SELECT count(*) AS pendientes FROM ingest.evaluation_queue WHERE failed_at IS NULL;
  SELECT count(*) AS sin_evaluar_120s FROM ingest.readings
  WHERE quality = 'ok' AND evaluated_at IS NULL AND received_at < now() - interval '120 seconds';"
```

The second query is SPEC's reliability NFR: it must return 0 when there are no pending failures.
