# ADR-0007: Live events emitted by Postgres triggers

- **Status:** Accepted on 2026-10-13
- **Date:** 2026-09-30
- **Related:** SPEC.md › Architecture › Real time to the dashboard; VIG-25; ADR-0002

## Context

The live map (VIG-25) needs to learn, in less than 2 s, about every change to an incident and every station heartbeat. SPEC sets the path: `NOTIFY willay_events` with the organization, a `LISTEN` connection in the API and SSE per organization to the dashboard.

Today incident events are inserted with SQL in ten places, spread across five files in two modules (incidents and alerts). Heartbeats are written by ingestion.

## Options

1. **`NOTIFY` in every place that inserts.** It is explicit, but fragile: every new piece of code that records an event has to remember to notify. If it forgets, the dashboard goes stale without anything failing or any test noticing.
2. **A `NOTIFY` in a shared repository.** It requires every path to go through that repository. Today they do not: the inserts live in each module's SQL, sometimes inside an `INSERT ... SELECT`.
3. **`AFTER INSERT`/`AFTER UPDATE` triggers on `core.incident_events` and `ingest.station_heartbeats`.**

## Decision

Option 3, in migration `0008`:

- `core.incident_events`: after each `INSERT`, a trigger notifies with `{organization_id, type: "incident", incident_id, event}`. Since every state change of an incident (opening, escalation, acknowledgement, resolution) leaves an event in the timeline, this table is enough.
- `ingest.station_heartbeats`: after each `INSERT` or `UPDATE`, another trigger notifies with `{organization_id, type: "station", station_id, last_seen_at, last_measured_at, last_value}`. The organization is looked up in `core.stations` by its PK, because the heartbeats table does not store it.
- `ingest.evaluation_queue` (added by VIG-39, migration 0009): when a row's `failed_at` changes, because the evaluator gave up on it or an operator reprocessed it, a trigger notifies with `{organization_id, type: "failed_readings"}` and the dashboard header refetches the count. A `WHEN` clause skips the evaluator's frequent claim updates without calling the function, and since Postgres delivers identical payloads once per transaction, reprocessing many rows sends a single notice.
- The notification carries just enough to route it and to know what to refresh. **Never personal data.** The dashboard requests the detail over REST, where permissions and per-role serialization apply.
- In the API, a single `LISTEN` connection per process fans the notifications out in memory: only to the SSE connections of that organization, each with its own bounded queue. If a client falls behind, or the connection to the database is lost, it receives `resync` and the dashboard requests everything again.
- The SSE stream is authenticated in a short transaction and closed when the token expires, so that an open dashboard neither holds on to a pool connection nor outlives its token.

## Consequences

- No code path, current or future, can forget to notify. The notification goes out in the same transaction as the change, and Postgres only delivers it if that transaction commits: nothing that ended in a rollback is ever announced.
- Part of the behavior lives in the database and cannot be seen by reading Python. This ADR, the comment in `shared/notifications.py` and an integration test that checks the notifications with the real ingestion and evaluation flow make up for it.
- One heartbeat per batch and station produces one notification. With the VIG-29 load (50 stations every 10 s) that is about 5 notifications per second, well within what `NOTIFY` handles.
- `NOTIFY` is not durable (ADR-0002): a notification emitted while the API is not listening is lost. That is why reconnecting triggers `resync`, and the dashboard always requests its state when it receives `ready`.
- If events ever move out of Postgres (see the criteria in ADR-0002), the triggers are replaced by an outbox and the contract with the dashboard (`ready`, `incident`, `station`, `failed_readings`, `resync`) does not change.
