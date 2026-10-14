# ADR-0002: PostgreSQL as queue, notification channel and rate limit

- **Status:** Accepted on 2026-10-13
- **Date:** 2026-09-26
- **Related:** SPEC.md › Architecture (No-loss guarantee, Rate limit); VIG-08, VIG-09, VIG-14

## Context

In an alerting system, a lost alert is worse than a duplicated one. Every accepted reading must be evaluated, even if a worker crashes halfway through. The latency target is p95 < 30 s from reading to alert. The MVP load is modest: 50 stations at one reading every 10 s is 5 readings per second.

The usual options (Redis, RabbitMQ, Kafka) add a service to operate and, above all, a consistency problem: saving the reading in Postgres and publishing it to a broker are two writes that can end up half done. Solving that requires the outbox pattern.

## Options

1. **Redis Streams or RabbitMQ**, with an outbox so as not to lose messages.
2. **Kafka**: oversized for 5 messages per second.
3. **Postgres**: an `ingest.evaluation_queue` table with `FOR UPDATE SKIP LOCKED`, `LISTEN/NOTIFY` to wake the workers and a windows table for the rate limit.

## Decision

Option 3, behind an `EvaluationQueue` interface so it can be replaced without touching the domain.

- **Atomic enqueueing:** the reading and its row in `evaluation_queue` are inserted in the **same transaction**. No outbox is needed.
- **Two transactions per row in the evaluator:**
  1. A short transaction claims the row (`available_at <= now`, `SKIP LOCKED`), increments `attempts`, sets `available_at = now + 60 s` (visibility timeout) and commits. The counter survives even if the worker dies.
  2. Another transaction evaluates, writes incidents and alerts, sets `readings.evaluated_at` and deletes the row. If the worker dies here, everything is rolled back and the row reappears when the timeout expires.
- **Poison rows:** with `attempts >= 5`, `failed_at` is set. The row leaves the partial index (`WHERE failed_at IS NULL`); the operator sees it in the dashboard and sends it back to the queue from there (VIG-39, `docs/runbooks/reprocess-failed-readings.md`).
- **Wake-up:** `NOTIFY` on enqueue and when alerts are created. Since `NOTIFY` is not durable (if nobody is listening, it is lost), the workers poll the queue every 5 s as a fallback.
- **Rate limit:** `ingest.rate_limit_windows` with one counter per station and minute, updated with an atomic upsert. It works with several API replicas. The `silence` worker purges windows older than 1 h.
- **Idempotency:** `UNIQUE (station_id, measured_at)` on the queue and the PK of `readings` prevent processing the same reading twice.

## Consequences

- **Pro:** one service fewer. No-loss guarantee with a single transaction. All the state can be queried with SQL, for example "zero `ok` readings without `evaluated_at` after 120 s", with its partial index.
- **Con:** the visibility timeout sets a 60 s floor for retries. An evaluation that takes longer than that could run twice, and incident idempotency (the unique index on `dedup_key`) covers it.
- **Con:** the queue competes with the rest of the Postgres load, and `LISTEN` takes up a dedicated connection per process.
- **Criteria for migrating to Redis Streams or Kafka:**
  - sustained p95 for claiming a row > 1 s;
  - more than ~500 readings per second;
  - queue table bloat that autovacuum cannot keep under control;
  - a need for several independent consumers of the same event.
