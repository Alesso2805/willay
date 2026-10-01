# ADR-0003: TimescaleDB for readings

- **Status:** Proposed (Sprint 0 draft)
- **Date:** 2026-09-26
- **Related:** SPEC.md › Database schema (`ingest.readings`); VIG-03

## Context

Readings are a time series that only grows: 50 stations at 1 reading every 10 s is about 430,000 rows a day. Rules query recent windows per station (the last N readings and the last T minutes). An incident's detail charts the readings around the event. Old readings lose operational value, but an incident's timeline must remain auditable.

## Options

1. **Postgres without extensions**, with hand-made declarative partitioning and our own purge jobs.
2. **A separate time-series database** (InfluxDB, for example): another service and another consistency model.
3. **TimescaleDB** on the same Postgres.

## Decision

Option 3. `ingest.readings` is a hypertable partitioned by `measured_at`:

- 1-day chunks;
- **columnstore** (compression) after 7 days, with `segmentby = station_id` and `orderby = measured_at DESC`, which matches the "one station in a window" query pattern;
- 180-day retention.

Rules that come with this decision:

- **Nothing points to `readings` with an FK**, because Timescale restricts FKs to hypertables. `evaluation_queue` stores `(station_id, measured_at)` without an FK. The FK from `readings` to `core.stations` is supported.
- **Evidence:** the `opened` event of each incident copies into its `payload` the readings that triggered the rule, so the timeline survives retention.
- **`evaluated_at`** makes it possible to verify that no `ok` reading was left unevaluated.

The current TimescaleDB 2.30 API is used: `add_columnstore_policy` and `timescaledb.enable_columnstore`. The `compression` names remain as legacy aliases.

## Consequences

- **Pro:** partitioning, compression and retention declared in the migration, with no jobs of our own. Queries in plain SQL and a single database.
- **Constrains deployment:** AWS RDS and Aurora do not offer TimescaleDB. The options are self-managed Postgres (container or VM) or Timescale Cloud. The reference image is `timescale/timescaledb-ha:pg16-ts2.30`.
- **License:** compression/columnstore and the retention policies are under the **Timescale License (TSL)**, not Apache 2.0. The TSL allows using them in your own product, but not offering TimescaleDB as a database service. It must be reviewed before any commercial use. The `-oss` variants of the image do not include these features.
- **Con:** inserting very late readings into already compressed chunks is more expensive. Readings more than 1 h late are marked `late` and are not enqueued (VIG-09).
