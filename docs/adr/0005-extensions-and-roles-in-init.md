# ADR-0005: DB extensions and roles in the Postgres init, not in Alembic

- **Status:** Proposed (Sprint 0 draft)
- **Date:** 2026-09-26
- **Related:** SPEC.md › Database roles; VIG-02, VIG-03; `infra/postgres/init/01-init.sh`

## Context

The original plan put extensions and roles in the initial migration, but it also required migrations to run as `vigia_owner`, a role without superuser privileges. The two things are incompatible:

- `timescaledb` and `postgis` **are not *trusted* extensions**: `CREATE EXTENSION` requires a superuser.
- A role cannot create itself, and granting `CREATEROLE` to `vigia_owner` would let it create arbitrary roles.

## Options

1. **Run Alembic as superuser.** Everything in one migration, but the `migrate` container would hold the most powerful credential.
2. **Grant `CREATEROLE` to `vigia_owner`** and create the extensions some other way.
3. **A Postgres init script**, which runs as superuser only once, on an empty volume.

## Decision

Option 3. `infra/postgres/init/01-init.sh`:

- creates the roles `vigia_owner`, `vigia_app` and `keycloak`, with passwords from environment variables;
- creates the databases `vigia` (owned by `vigia_owner`) and `keycloak` (owned by `keycloak`);
- revokes `CONNECT` from `PUBLIC` on both databases;
- creates the `timescaledb` and `postgis` extensions in `vigia`.

Migration `0001` runs `CREATE EXTENSION IF NOT EXISTS` as a **check**: if the extension exists, it does nothing; if it is missing, it fails on permissions and `migrate` exits with an error, which prevents the API and the workers from starting.

Migration `0001` also sets `ALTER DEFAULT PRIVILEGES FOR ROLE vigia_owner` **before** creating any table. That way the 20 initial tables and those of future migrations get their permissions for `vigia_app` through the same mechanism, and the "future table" test exercises the path the whole schema uses.

## Consequences

- **Pro:** `migrate` only has the `vigia_owner` credential. The API and the workers only have the `vigia_app` one.
- **Pro:** the integration tests mount the same script in the testcontainers container, so they test exactly the production permissions.
- **Con:** the init only runs with an empty volume. Changing roles or extensions in an existing database requires a manual runbook. For development, `docker compose down -v` is enough.
- **Con:** on a managed Postgres (Timescale Cloud, for example) this script does not run, and its content must be applied by whoever administers the instance. It will go in `docs/runbooks/`.
- **Note:** the script must have LF line endings (`.gitattributes`) and the executable bit in git, or the entrypoint loads it with `source` instead of executing it.
