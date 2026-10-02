# Reprocess readings that failed in the evaluator

A reading ends up with `failed_at` when the evaluator failed 5 times to evaluate it (ADR-0002). It leaves the queue so as not to block it, but **it was not evaluated**: if it triggered a rule, that alert did not go out. You have to review the cause and reprocess it.

While there is any, every page of the dashboard shows a notice with the count to operators and admins ("N lecturas no se pudieron evaluar…"). It appears and disappears live (VIG-39).

## 1. See what failed and why

Open the notice's link, **Ver lecturas fallidas** (`/lecturas-fallidas`). Each row shows the station, the measurement (value and local time), the attempts, when it failed and the last error.

If the last error says `sin completar tras 5 intentos` ("not completed after 5 attempts"), the worker died during the last attempt (restarts, memory, deployments) and there was no rule error.

## 2. Fix the cause

- **Error in a rule** (e.g. inconsistent parameters): fix the rule from the dashboard or deploy the evaluator fix.
- **Database or network down** during the 5 attempts: reprocessing is enough.

Do not reprocess without fixing: it will fail 5 times again.

## 3. Send them back to the queue

Select the readings (or **Seleccionar todas**) and press **Reprocesar seleccionadas**. They go back to the queue with their attempts reset, and the evaluator is woken up at once (`NOTIFY`), so it takes them within seconds. The action is recorded in the audit log, once per station, with each measurement and the error it had.

## 4. Verify

The readings disappear from the list and the notice goes away. If any fails again, it comes back to the list with its new error.

## Without the dashboard

If the dashboard is unavailable, the same steps in SQL:

```bash
# 1. What failed and why
docker compose exec postgres psql -U postgres -d willay -c "
  SELECT q.id, s.code, q.measured_at, q.attempts, q.failed_at, q.last_error
  FROM ingest.evaluation_queue q JOIN core.stations s ON s.id = q.station_id
  WHERE q.failed_at IS NOT NULL
  ORDER BY q.failed_at DESC;"

# 3. Back to the queue (this path leaves no audit entry: note who did it and why)
docker compose exec postgres psql -U postgres -d willay -c "
  UPDATE ingest.evaluation_queue
  SET failed_at = NULL, attempts = 0, available_at = now()
  WHERE failed_at IS NOT NULL
    AND id IN (/* ids from step 1 */);
  NOTIFY willay_evaluation_queue;"

# 4. Nothing left behind
docker compose exec postgres psql -U postgres -d willay -c "
  SELECT count(*) AS pendientes FROM ingest.evaluation_queue WHERE failed_at IS NULL;
  SELECT count(*) AS sin_evaluar_120s FROM ingest.readings
  WHERE quality = 'ok' AND evaluated_at IS NULL AND received_at < now() - interval '120 seconds';"
```

The last query is SPEC's reliability NFR: it must return 0 when there are no pending failures.
