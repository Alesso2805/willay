# Architecture Decision Records

One technical decision per file: context, options, decision and consequences. Any decision not covered by [SPEC.md](../SPEC.md) is recorded here with the next free number (`NNNN-title.md`).

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-single-python-backend.md) | Single Python backend with separate modules and workers | Proposed |
| [0002](0002-postgres-as-queue.md) | PostgreSQL as queue, notification channel and rate limit | Proposed |
| [0003](0003-timescaledb-for-readings.md) | TimescaleDB for readings | Proposed |
| [0004](0004-keycloak-organizations-tenant.md) | Keycloak 26 Organizations as the source of tenant and roles | Proposed |
| [0005](0005-extensions-and-roles-in-init.md) | DB extensions and roles in the Postgres init | Proposed |
| [0006](0006-sql-migrations-and-testcontainers.md) | Migrations in explicit SQL and tests with testcontainers | Proposed |
| [0007](0007-live-events-with-triggers.md) | Live events emitted by Postgres triggers | Proposed |

Statuses: Proposed → Accepted → (Superseded by ADR-NNNN | Deprecated).
