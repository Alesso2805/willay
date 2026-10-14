# ADR-0006: Migrations in explicit SQL and integration tests with testcontainers

- **Status:** Accepted on 2026-10-13
- **Date:** 2026-09-26
- **Related:** SPEC.md › Database schema; Definition of done; VIG-03

## Context

The schema uses DDL that Alembic cannot autogenerate: hypertables, columnstore and retention policies, PostGIS geometries, partial unique indexes, `ALTER DEFAULT PRIVILEGES` and `REVOKE`. In addition, the definition of done requires integration tests against a **real Postgres**, with the production extensions and roles.

## Decision

### Migrations

- They are written **by hand with `op.execute()` and explicit SQL**. There is no `target_metadata` and no autogenerate. Each module's SQLAlchemy models will arrive with their stories and must match the migrations, not generate them.
- **Closed sets of values with `text` + `CHECK`, not with `ENUM` types.** Adding a value to an `ENUM` is easy, but removing or renaming one is not. A `CHECK` is replaced in a normal migration.
- One transaction per migration (`transaction_per_migration=True`): if `0003` fails, `0001` and `0002` stay applied. This was seen in practice during VIG-03.
- Revisions with readable ids (`0001`, `0002`…) and `downgrade()` in all of them. A test runs `upgrade head` → `downgrade base` → `upgrade head`.
- The uuid v7 PKs **have no `DEFAULT`**: the application generates them with `uuid-utils`, because PostgreSQL 16 has no `uuidv7()`.

### Integration tests

- **testcontainers** starts, per pytest session, the **same image** as Docker Compose (`timescale/timescaledb-ha:pg16-ts2.30`) with the **same init script**, and applies the migrations as `willay_owner`.
- There are `owner` and `app` fixtures (asyncpg connections with each role), so the permission tests use the API's real role.
- Each test creates its own organization with new uuids. The database is shared and does not need cleaning (nor could it be cleaned in the append-only tables).
- Alembic runs in its own thread, because `env.py` uses `asyncio.run()` and pytest-asyncio already has an event loop running.
- The `integration` marker allows `pytest -m "not integration"` for a quick pass without Docker.

## Consequences

- **Pro:** the migration SQL is exactly what runs in production, readable and reviewable in the PR. The tests exercise real permissions, indexes and constraints, not SQLite or a mock.
- **Con:** without autogenerate there is no automatic detection of drift between models and schema. Mitigation: integration tests that use the real repositories against the migrated database.
- **Con:** the integration tests need Docker. The GitHub Actions runner has it, and the session container adds a few seconds (≈ 8 s for the full suite locally).
