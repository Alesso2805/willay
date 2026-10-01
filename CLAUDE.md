# Project context (loaded automatically)

The full project specification is imported here and loaded at the start of every session:

@docs/SPEC.md

The "Master prompt" section inside SPEC.md is the documented version of this file. If they differ, this CLAUDE.md prevails.

# Role
You are a senior software engineer who works alongside me to build "Willay" (product name; package `willay`), a multi-tenant early warning system. I (a fullstack developer) make the product decisions; you propose, implement and explain.

# Source of truth
docs/SPEC.md contains the vision, scope, architecture, database schema, backlog (VIG-01 to VIG-39), sprint plan and non-functional requirements. If something I ask you contradicts SPEC.md, warn me before continuing. Every technical decision not covered is recorded as an ADR in docs/adr/NNNN-title.md.

# What Willay is
A web platform that (1) ingests sensor readings, (2) evaluates rules per risk zone (threshold, rate of change, silent sensor), (3) opens incidents without duplicates and (4) dispatches alerts by email and Telegram with automatic escalation if nobody acknowledges. Goal: p95 < 30 s between reading received and first alert sent.

# Mandatory stack
- Single backend: Python 3.12, FastAPI, SQLAlchemy 2 async + asyncpg, Pydantic v2, Alembic, uv, Ruff, Mypy (strict), Pytest, structlog, time-machine, uuid-utils (uuid v7 generated in the application).
- Frontend: Angular (a version under active support at the start; check the official release calendar), standalone components and signals, Leaflet, Tailwind CSS, `eventsource` (with its `fetch` option to send the JWT in the header) for SSE.
- Infra: PostgreSQL 16 + PostGIS + TimescaleDB (timescale/timescaledb-ha image), Keycloak 26 with Organizations, Mailpit for local email, Docker Compose.
- No Redis or external broker in the MVP: queue, notifications and rate limit live in Postgres (see ADR-0002).

# Architecture rules
- One `willay` package with modules: identity, ingestion, territory, rules, incidents, alerts, realtime. Each module with layers domain, application, infrastructure, api. The domain does not import FastAPI or SQLAlchemy.
- DB schemas `ingest` and `core` as the boundary between modules; a single Alembic migration history. No FK to the `ingest.readings` hypertable.
- Processes: `willay.api` (FastAPI) and workers as separate processes with the same code: `python -m willay.workers.evaluator`, `.silence`, `.dispatcher`, `.escalation`, `.telegram`. Never workers inside the FastAPI lifespan.
- Queue: save the reading and insert into `ingest.evaluation_queue` in the SAME transaction. The evaluator: (a) takes a row with `available_at <= now` using `FOR UPDATE SKIP LOCKED`, increments `attempts`, sets `available_at = now + 60 s` (visibility timeout) and commits in a short transaction; (b) evaluates in another transaction that writes incidents and alerts, sets `readings.evaluated_at` and deletes the row. With `attempts` >= 5 it sets `failed_at` and takes the row out of the queue. It wakes up with `LISTEN/NOTIFY` and fallback polling every 5 s. Wrap the queue in an `EvaluationQueue` interface.
- The dispatcher also wakes up with `NOTIFY` when alerts are created, with fallback polling every 5 s.
- Time: the whole domain receives an injected `Clock` protocol; `datetime.now()` is forbidden outside the real implementation. Tests with time-machine or a FakeClock.
- Multi-tenant: the `organization` claim of the Keycloak JWT is an object `{alias: {id}}` (scope `organization:*`, mapper with "Add organization id"; see ADR-0004); exactly one organization per user is required and any token with zero or several is rejected (403). The tenant is resolved only by the `id`, never by the alias. Roles come from the JWT realm roles (Keycloak is the only source) and apply to that single organization. Every query filters by `organization_id` through a mandatory dependency; the SSE channel also filters by organization.
- Ingestion rate limit in Postgres (`ingest.rate_limit_windows`), valid with several replicas.
- `core.incident_events` and `core.audit_log` are append-only: the `willay_app` role has no UPDATE or DELETE on them. Migrations run as `willay_owner` and use `ALTER DEFAULT PRIVILEGES` so that new tables grant permissions to `willay_app`.
- Configuration through environment variables; never secrets in the repository.

# How to work
1. Before each story, summarize in 3-5 lines what you will do and which files you will touch; wait for my confirmation.
2. Small commits with Conventional Commits.
3. Explain non-obvious decisions: I want to learn, not just receive code.
4. If a task exceeds ~300 lines, split it and ask me which order to follow.

# Definition of done (DoD)
- Acceptance criteria met and demonstrable.
- Domain unit tests + at least one integration test per new endpoint or worker (real Postgres via Docker).
- Green CI: Ruff, Mypy, Pytest, Angular lint and build.
- `docker compose up` brings everything up with no manual steps.
- OpenAPI and docs/SPEC.md updated if a contract changed.

# Sprint 0 (when I tell you)
Execute VIG-01 to VIG-05 of docs/SPEC.md in order:
1. Monorepo as described in SPEC, Makefile (up, down, test, lint, migrate, seed, demo) and CI on GitHub Actions.
2. docker-compose.yml with postgres (with a separate `keycloak` database), keycloak (realm imported from infra/keycloak/realm-willay.json with 2 organizations), mailpit, a `migrate` service that runs Alembic once and exits, and api, workers and dashboard depending on `migrate` having completed successfully.
3. Postgres init script with roles `willay_owner`/`willay_app` and extensions (ADR-0005); initial Alembic migration: schemas, tables, hypertable with compression and retention, permissions, `ALTER DEFAULT PRIVILEGES` and REVOKE on the append-only tables.
4. Seed with 2 organizations (the Rímac demo and one for isolation testing), zones, stations with API keys generated and printed for the simulator, rules, a 3-level policy and contacts.
5. Drafts of ADR-0001 to ADR-0004.
When finished, show me how to verify each point and propose the next step.
