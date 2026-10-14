# ADR-0001: Single Python backend with separate modules and workers

- **Status:** Accepted on 2026-10-13
- **Date:** 2026-09-26
- **Related:** SPEC.md › Architecture; Repository, conventions and living documentation

## Context

Willay needs HTTP ingestion, rule evaluation, silence detection, alert delivery over two channels, escalation and an SSE channel to the dashboard. It is built and maintained by a single person outside working hours, in 7 two-week sprints. The candidate phase 3 (predictive models for huaicos, the debris flows common in Peru) would be done in Python.

The processes have very different profiles: the API answers in milliseconds, the evaluator consumes a queue, the Telegram worker does long polling and the escalation worker runs every 15 s. If they fail together, an outage of the SMTP provider could stall the evaluation of readings.

## Options

1. **Three services** (ingestion, rules/incidents, alerts), each with its own repository or image, communicating over the network.
2. **A monolith** with the workers as tasks inside the FastAPI lifespan.
3. **A single Python package (`willay`) deployed as several processes**: the API and the workers with the same code and image, run with `python -m willay.workers.<name>`.

## Decision

Option 3. A `willay` package with the modules `identity`, `ingestion`, `territory`, `rules`, `incidents`, `alerts` and `realtime`. Each module has the layers `domain`, `application`, `infrastructure` and `api`, and the domain does not import FastAPI or SQLAlchemy. The database schemas `ingest` and `core` mark the boundary between modules.

Workers never run inside the FastAPI lifespan. In Docker Compose, a single image (`willay-backend`) serves `api`, `migrate` and the workers, and only the command changes. There are six: `evaluator`, `silence`, `dispatcher`, `escalation` and `telegram`, plus `demo`, which only runs for the public demo (VIG-43, Compose profile `demo`).

## Consequences

- **Pro:** a single `pyproject.toml`, a single `uv.lock`, a single CI pipeline, and refactors that cross modules in one commit. Each process scales and fails on its own. `SKIP LOCKED` spreads the work across replicas of the same worker.
- **Pro:** the code of the predictive phase can import the domain without an intermediate API.
- **Con:** the boundaries between modules depend on discipline. Future mitigation: an import-contracts tool (for example import-linter) in CI once there is real domain code.
- **Con:** the workers do not expose HTTP. Their healthcheck is a heartbeat file that the worker touches on every cycle, and `python -m willay.workers.healthcheck <name>` checks that it is less than 30 s old.
- **Way out:** if a module needs to be split off, its database schema and its interfaces (for example `EvaluationQueue`) already mark the cut.
