# Architecture Decision Records

One technical decision per file: context, options, decision and consequences. Any decision not covered by [SPEC.md](../SPEC.md) is recorded here with the next free number (`NNNN-title.md`).

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-single-python-backend.md) | Single Python backend with separate modules and workers | Accepted |
| [0002](0002-postgres-as-queue.md) | PostgreSQL as queue, notification channel and rate limit | Accepted |
| [0003](0003-timescaledb-for-readings.md) | TimescaleDB for readings | Accepted |
| [0004](0004-keycloak-organizations-tenant.md) | Keycloak 26 Organizations as the source of tenant and roles | Accepted |
| [0005](0005-extensions-and-roles-in-init.md) | DB extensions and roles in the Postgres init | Accepted |
| [0006](0006-sql-migrations-and-testcontainers.md) | Migrations in explicit SQL and tests with testcontainers | Accepted |
| [0007](0007-live-events-with-triggers.md) | Live events emitted by Postgres triggers | Accepted |
| [0008](0008-i18n-with-i18next.md) | The dashboard in several languages with i18next | Accepted |
| [0009](0009-light-and-dark-mode-with-css-variables.md) | Light and dark mode with CSS variables | Accepted |
| [0010](0010-deploy-on-one-server-behind-caddy.md) | Deploy on one server, behind Caddy, on one hostname | Accepted |
| [0011](0011-wrong-api-keys-limited-in-the-api.md) | Wrong API keys limited per address, in the API | Accepted |

Statuses: Proposed → Accepted → (Superseded by ADR-NNNN | Deprecated).
