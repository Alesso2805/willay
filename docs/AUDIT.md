# Willay architecture audit

Date: 2026-10-12 · Commit audited: `1ff8e5f` (branch `main`, clean working tree at the start).

Updated on 2026-10-13 with the runs made after the first pass (sections 2.1, 3 for VIG-08 and VIG-29, and 8). They come from two machines: **machine A**, where the audit was written (Docker Desktop with 4 CPUs and 3.8 GiB), and **machine B** (20 CPUs; for the load test its Docker was limited to 4 CPUs and 3.8 GiB, like machine A's).

## How this audit was done, and its limits

- **Documents named in the brief that do not exist.** `docs/BACKLOG.md` and `docs/ARCHITECTURE_RULES.md` are not in the repository. I audited against what does exist: the backlog is the "Product backlog" table in `docs/SPEC.md`, and the architecture rules are the "Architecture rules" section of `CLAUDE.md` (the "Master prompt" section of SPEC repeats a slightly older copy). Either create those two files or correct the brief.
- **What I executed myself:** on machine A, `ruff check`, `ruff format --check`, `mypy` (all clean), the full backend `pytest` (a full run, then the four failures re-run alone), `make up` and `make seed` against the working tree. After the first pass: the full suite twice more on machine A (section 2.1), `make loadtest` on both machines (section 3, VIG-29), and on machine B the dashboard's lint, tests and build.
- **What I did not execute:** a `make up` from a fresh clone, `make demo` and the production deployment. Machine A has Node 22.16 and the dashboard requires `^24.15.0`, so the dashboard's checks ran on machine B.
- **What was delegated:** four read-only sub-audits (structure and coupling, schema and ADRs, backend stories, dashboard stories) did the grepping and test reading. Where a row says "by name" the test was judged from its name and a grep, not from reading its body. Rows marked "no verificado" were not confirmed.
- **Not audited:** VIG-06 and VIG-07 (identity and roles) beyond a few tests seen incidentally, VIG-31, VIG-32 (optional) and VIG-45 (license and README). They are listed as "no verificado" in section 3.

Status vocabulary: **Cumple** (meets), **Parcial** (partly), **No cumple** (does not), **No verificable / no verificado** (could not be confirmed by reading code or running tests).

---

## 1. Repository structure

SPEC tree (`docs/SPEC.md`, "Repository, conventions and living documentation") against the real tree.

| Item | Status | Detail |
| --- | --- | --- |
| Top-level layout (`backend/`, `dashboard/`, `infra/`, `docs/`, compose, Makefile, CLAUDE.md, CHANGELOG, README) | Cumple | All present. |
| Seven modules each with `domain/application/infrastructure/api` | Cumple | No module lacks a layer. Some are thin: `realtime/` has one file per layer, `incidents/api` has only `routes.py`. |
| `shared/` content | Cumple | SPEC says "Clock, config, db, tenancy, logging". There is no `shared/tenancy`; tenancy lives in `identity` (`identity/domain/principal.py`). `shared/` also holds `audit, i18n, languages, notifications, pg_listen, web, errors`, which SPEC does not list. **Update, 2026-10-13:** SPEC now says so. |
| Runbooks | Parcial | SPEC promises reprocess, rotate API keys and restore the DB. Only `deploy.md` and `reprocess-failed-readings.md` exist. **Missing:** rotate API keys, restore the DB. |
| `docs/research/` | Cumple | Only `.gitkeep`. Consistent with the 2026-09-30 decision to postpone interviews. |
| Things in the repo that SPEC's tree does not show | Cumple | `backend/src/willay/{demo,loadtest,seed}/` and `api/openapi.py` (no layering), `backend/tests/support/`, `docker-compose.prod.yml`, `infra/caddy/`, `infra/scripts/production-env.sh`, `.env.example`, `.github/workflows/ci.yml`, `docs/openapi.json`, `docs/images/`, ADRs 0005 to 0010, `backend/Dockerfile`, `alembic.ini`, `uv.lock`. Most are explained by later stories (VIG-42/43) but the SPEC tree was not updated. **Update, 2026-10-13:** SPEC now says so. |

Section 1: 5 Cumple · 1 Parcial · 0 No cumple.

---

## 2. Architecture rules

### 2.1 Architecture tests: result

There are **no architecture tests**. No import-linter, pytest-archon, grimp or AST-based test exists in `pyproject.toml`, the Makefile, CI or `backend/tests`. The only mechanically enforced rule is the clock ban, done by Ruff (`backend/pyproject.toml:52-65`, rules `DTZ` and `TID251`, with a per-file ignore for `shared/clock.py`). So "run the architecture tests" has no answer: I ran the whole suite instead.

**Real test results (`uv run pytest`, full suite, machine A, Windows + Docker Desktop):**

- **First run, ~10 min, with another project's containers running on the same Docker:** 973 passed, **4 failed**:
  - `test_audit_api.py::test_invalid_queries_get_422_on_their_field[params0-cursor]`
  - `test_demo_api.py::test_a_playing_scenario_says_where_the_story_is`
  - `test_email_dispatch.py::test_the_worker_emails_level_one_and_the_link_confirms_it`
  - `test_enqueue_and_notify.py::test_nothing_enqueued_means_no_notification[only-duplicates]`

  I only read the traceback of one of them: a `ConnectionResetError [WinError 64]` from asyncpg while connecting. Re-running the four alone gave **8 passed** (the parametrised cases included).
- **The same suite with that other project stopped:** **977 passed, 0 failed.**
- **With the API key cache (section 3, VIG-29), which adds five tests:** **982 passed, 0 failed**, in 7 min 2 s.

The four failures appeared only while another project competed for the same 4 CPUs and 3.8 GiB, which points to resource contention rather than a defect. That rests on one run each way: suggestive, not proof. Also: `ruff check` clean, `ruff format --check` clean (317 files), `mypy` clean (316 files).

### 2.2 Rules from CLAUDE.md

| # | Rule | Status | Evidence |
| --- | --- | --- | --- |
| 1 | One `willay` package, modules with four layers | Cumple | Directory listing, section 1. |
| 2 | The domain does not import FastAPI or SQLAlchemy | Cumple (not enforced by a test) | Grep of every `*/domain` found no `fastapi/sqlalchemy/starlette/asyncpg/psycopg` import. Nothing prevents a regression. |
| 3 | Schemas `ingest` and `core`, single migration history | Cumple | `migrations/versions/0001..0014`; `test_schema.py::test_all_tables_exist` (core 17, ingest 4). |
| 4 | No FK to `ingest.readings` | Cumple (grep only) | No `REFERENCES ... readings` in migrations (grep; I did not read every migration in full). `evaluation_queue` has no FK to readings (`0003:75-76`). |
| 5 | API and workers are separate processes; never workers in the FastAPI lifespan | Cumple | `api/main.py:49-72` starts only a `PgEventListener` (SSE feed, `:64`), no worker. Workers in `workers/` with `_runner.py`. |
| 6 | Reading and queue row in the same transaction | Cumple | `test_ingestion_api.py::test_batch_is_stored_and_enqueued_in_the_same_transaction`; `test_enqueue_and_notify.py::test_rolled_back_batch_never_notifies`. |
| 7 | Evaluator: `SKIP LOCKED`, `attempts` in its own transaction, 60 s visibility, `failed_at` at 5 | Cumple | `rules/infrastructure/pg_queue.py:16-47`; `test_evaluation_queue.py` (claim hides rows, two evaluators never claim the same row, fifth attempt sets `failed_at`); `test_evaluator_worker.py::test_killing_the_worker_mid_evaluation_leaves_the_row_for_a_retry`. |
| 8 | Wakes with `LISTEN/NOTIFY`, fallback polling every 5 s | Parcial | NOTIFY wake proved by `test_a_notify_wakes_the_worker_long_before_the_polling_interval`. The default poll interval being 5 s is no verificado (tests use 0.05 s). |
| 9 | `EvaluationQueue` interface | Cumple | `rules/application/queue.py` (interface) and `rules/infrastructure/pg_queue.py` (`PostgresEvaluationQueue`). Judged by file and class names. |
| 10 | Dispatcher wakes with `NOTIFY` and polls | Cumple | `test_alert_planning.py::test_the_dispatcher_is_woken_when_the_incident_commits`; `test_email_dispatch.py` (poll interval 60 s, so only a NOTIFY wake can deliver). |
| 11 | Injected `Clock`; `datetime.now()` forbidden outside the real clock | Cumple | Only `shared/clock.py:21`; Ruff ban at `pyproject.toml:57-65`. |
| 12 | `organization` claim is an object `{alias:{id}}`; exactly one; 403 otherwise; resolved by `id` | Cumple | `identity/domain/principal.py:63-81`; `identity/application/authenticate.py:48-49`; `test_identity_api.py::test_anything_but_one_registered_organization_gets_403`. The exact 403 mapping was not read. |
| 13 | Roles from JWT realm roles only | Cumple | `realm_access` is read in identity (ADR-0004); `users` has no role column. Per-role 403 coverage is by test names only. |
| 14 | Every query filters by `organization_id` through a mandatory dependency | No verificado | Per-endpoint isolation tests exist for the endpoints audited (zones, stations, rules, incidents, contacts, groups, audit, failed readings, organization), but nothing enforces it structurally and I did not read every repository query. |
| 15 | SSE channel filtered by organization | Cumple | `test_events_api.py::test_each_organization_only_hears_its_own_events_within_two_seconds`; `test_realtime.py::test_events_only_reach_their_own_organization`. |
| 16 | Rate limit in `ingest.rate_limit_windows`, valid with replicas | Cumple | `ingestion/infrastructure/repositories.py:55-58`; `test_rate_limit_api.py::test_limit_is_shared_by_two_api_replicas_under_concurrency`. |
| 17 | `incident_events` and `audit_log` append-only for `willay_app` | Cumple | `0002:329-331`; `test_db_privileges.py::test_app_cannot_update_or_delete_append_only_tables`. |
| 18 | Migrations as `willay_owner`; `ALTER DEFAULT PRIVILEGES` | Cumple | `0001:36-39`; `test_db_privileges.py::test_table_created_later_by_owner_is_granted_to_app`. |
| 19 | Configuration via environment; no secrets in the repo | No verificado | `.env` is untracked and `.secrets/` is ignored (git status was clean). I did not scan history or the realm JSON for secrets. `.env.example` carries development-only credentials by design. |
| 20 | Mandatory stack (Python 3.12, FastAPI, SQLAlchemy async, Pydantic v2, uv, Ruff, Mypy strict, Postgres 16 + Timescale, Keycloak 26.7.4, Mailpit, `eventsource`) | Cumple | `requires-python >=3.12,<3.13`; `docker-compose.yml:26,48`; Angular 22.2, `eventsource ^5.1.2`. Mypy "strict" setting itself was not opened; mypy passes. |
| 21 | Architecture tests for these rules | No cumple | Section 2.1. |
| 22 | Cross-module layering (no layer reaches into another module's internals) | Parcial | Not an explicit CLAUDE.md rule, but the module/layer scheme implies it. Violations in section 7. |
| 23 | DoD: green CI (Ruff, Mypy, Pytest, Angular lint and build) | Cumple | Ruff, Mypy and Pytest green (982/982 with nothing else on Docker, section 2.1). Angular lint, tests (331) and build green on machine B with Node 24.21. |

Section 2: 18 Cumple · 2 Parcial · 1 No cumple · 2 No verificado (23 items).

---

## 3. Stories: acceptance criteria and their tests

Notation: `u/` = `backend/tests/unit`, `i/` = `backend/tests/integration`, `FE` = `dashboard/src/app`. Status: OK = a test asserts it, P = only part, NO = no test found. "By name" caveat as above.

### Sprint 0

- **VIG-01** (OK 1, P 2, NO 1). Structure as in SPEC → no test (NO). `make lint` passes → `ci.yml` backend and dashboard jobs run the underlying commands, not `make lint` (P). `make test` passes → same (P). Actions runs Ruff, Mypy, Pytest, Angular build → `ci.yml` steps (OK). Extra: `u/test_openapi_contract.py::test_committed_openapi_matches_the_app`.
- **VIG-02** (OK 2, P 2, NO 2). `make up` brings up everything → `ci.yml` `compose` job uses `docker compose up --wait`, not `make up` (P). Separate keycloak DB → created by `01-init.sh`, no assertion (NO). migrate runs once and exits → CI step "migrate finished successfully", ExitCode 0 (OK). API and workers wait for migrate → `depends_on: service_completed_successfully`, proved only indirectly (P). Healthchecks green → `--wait` (OK). "5 workers" → compose has **6** (adds `demo`); no count check (NO).
- **VIG-03** (OK 4, P 1). Roles and extensions in init → exercised indirectly by every integration test, no direct test (P). Schemas and tables → `i/test_schema.py::test_all_tables_exist` (OK). Hypertable, compression, retention → `test_readings_is_a_hypertable_with_columnstore_and_retention` (OK). `willay_app` cannot UPDATE `incident_events` → `i/test_db_privileges.py::test_app_cannot_update_or_delete_append_only_tables` (OK). Permissions on a later table → `test_table_created_later_by_owner_is_granted_to_app` (OK).
- **VIG-04** (OK 2, P 2). 2 orgs, 3 zones, 10 stations, 6 rules, 5 contacts → `i/test_seed.py::test_seed_creates_expected_data_and_is_idempotent` (OK). One policy per org, 3 levels in Rímac → same test (OK). 1 level in the isolation org → not asserted (P). Keys printed → rotation and verification tested, printing and the keys file only by the CI smoke step (P). I ran `make seed` myself: it printed 10 keys.
- **VIG-05** (P 1, NO 1). ADR-0001 to 0004 exist → files present, no test (NO, documentation). ADR-0004 documents the mapper → documented; behaviour covered by `i/test_identity_api.py::test_each_seed_organization_sees_itself` (P).

### Sprint 1

- **VIG-06, VIG-07:** no verificado. Tests seen incidentally: `test_identity_api.py::test_each_seed_organization_sees_itself`, `::test_anything_but_one_registered_organization_gets_403`, and per-role tests in other APIs.
- **VIG-08** (OK 6, P 1). Up to 500 → `i/test_ingestion_api.py::test_a_full_batch_of_500_is_accepted` (OK). Argon2id → `u/test_api_keys.py::test_hash_is_argon2id_and_verifies_only_the_right_key` (OK). 401 → `test_missing_or_invalid_key_gets_401` (OK). 422 → `test_invalid_batches_get_422_and_store_nothing` (OK). 429 over 60/min → `i/test_rate_limit_api.py::test_limit_is_shared_by_two_api_replicas_under_concurrency` (OK). Counted in `rate_limit_windows` → the table is not asserted directly (P). Two replicas → same test (OK). Since the VIG-29 fix the API remembers a verified key per process (never a failure), and rotation still revokes the old key at once → `u/test_api_keys.py` (five tests on the cache) and `i/test_stations_api.py::test_rotating_the_key_revokes_the_old_one_at_once`, which now uses the old key before rotating it, so the key is in the cache when rotation must stop it.
- **VIG-09** (OK 4). Same transaction → `test_batch_is_stored_and_enqueued_in_the_same_transaction`. NOTIFY → `i/test_enqueue_and_notify.py::test_accepted_batch_wakes_up_the_evaluator`. Duplicates ignored → `test_resending_readings_does_not_duplicate_them_or_their_queue_rows`. Late readings → `test_late_readings_are_stored_but_not_enqueued`.
- **VIG-10** (OK 3). Upsert → `i/test_heartbeat_api.py::test_first_batch_creates_the_heartbeat_from_the_latest_on_time_reading`. Late-only batch → `test_a_batch_of_only_late_readings_does_not_beat`. Concurrency → `test_concurrent_batches_from_two_replicas_never_move_the_heartbeat_back`.
- **VIG-11** (OK 3, P 1). CLI with scenarios, `--stations`, `--seed` → domain and runner tested (`u/test_simulation.py`, `u/test_simulate_runner.py`), argparse in `simulator_cli.py` not tested, CI smoke runs it once (P). Feeds the real API → `i/test_simulator.py::test_simulated_station_feeds_the_real_api` (OK). Reproducible → `u/test_simulation.py::test_same_seed_gives_the_same_series` (OK). Rímac scenario → `test_rimac_scenario_drops_downstream_then_silences_upstream_four_minutes_later` (OK).

### Sprint 2

- **VIG-12** (OK 3; Leaflet drawing is dashboard, not audited). CRUD → `i/test_zones_api.py::test_operator_creates_a_zone_and_it_is_audited` and related. Geometry validation → `test_invalid_polygons_get_422_with_the_reason_and_nothing_is_saved`. Audit → `u/test_zones_use_cases.py::test_update_audits_before_and_after`.
- **VIG-13** (OK 4). CRUD, positions, key shown once, stations without zone flagged → `i/test_stations_api.py` (`test_created_station_gets_a_working_key_shown_once`, `test_rotating_the_key_revokes_the_old_one_at_once`, `test_stations_without_zone_are_marked`).
- **VIG-14** (OK 8, P 1). Separate process → the test runs `run_evaluator` as asyncio tasks, not an OS process; compose health only (P). `SKIP LOCKED` → `i/test_evaluation_queue.py::test_two_evaluators_never_claim_the_same_row`. LISTEN/NOTIFY → `i/test_evaluator_worker.py::test_a_notify_wakes_the_worker_long_before_the_polling_interval`. attempts and 60 s → `test_claim_hides_rows_for_the_visibility_timeout`. `evaluated_at` and delete → `test_complete_marks_evaluated_and_removes_the_row_in_the_same_transaction`. Kill mid-evaluation → `test_killing_the_worker_mid_evaluation_leaves_the_row_for_a_retry`. Two evaluators → `test_two_workers_evaluate_every_row_exactly_once`. Fifth attempt → `test_a_row_that_always_fails_is_marked_failed_at_the_fifth_attempt`. Injected clock → FakeClock in these tests, `u/test_clock.py`.
- **VIG-15** (OK 2). N consecutive → `i/test_threshold_rules.py::test_two_consecutive_readings_above_the_limit_open_one_incident`, `u/test_threshold.py::test_fires_only_with_n_consecutive_breaches`. Boundary → `u/test_threshold.py::test_limit_is_exact_at_the_boundary`.
- **VIG-16** (OK 3). Rise and drop → `u/test_rate_of_change.py`, `i/test_rate_of_change_rules.py::test_an_up_rule_fires_on_a_sudden_rise`. Only `ok` → `test_late_readings_are_not_part_of_the_window`. Drop scenario → `test_the_drop_scenario_opens_one_incident_at_the_drop`.

### Sprint 3

- **VIG-17** (OK 6, P 1). Worker every 15 s → `INTERVAL_S = 15.0` in `workers/silence.py`, no test asserts it (P). One incident per silent station → `i/test_silence_worker.py::test_a_zone_wide_rule_opens_one_incident_per_silent_station`. Before K × interval + 30 s → `test_the_incident_opens_before_k_times_the_interval_plus_30_s`. No zone no alert → `test_stations_that_cannot_alert_are_ignored`. `station_recovered` → `test_a_station_that_reports_again_gets_station_recovered_once`. Purge → `test_the_worker_process_opens_the_incident_and_purges_old_windows`. FakeClock → these tests.
- **VIG-18** (OK 4). Unique index → `i/test_schema.py::test_only_one_active_incident_per_dedup_key`. Cooldown → `i/test_incident_lifecycle.py::test_a_resolved_cause_does_not_reopen_during_its_cooldown`. Evidence copy → `test_two_consecutive_readings_above_the_limit_open_one_incident` (payload). Race → `test_two_evaluators_racing_on_the_same_cause_open_one_incident`.
- **VIG-19** (OK 4). Transitions → `u/test_incident_lifecycle.py::test_transitions`. 409 → `i/test_incidents_api.py::test_invalid_transitions_get_409`. CHECK → `i/test_schema.py::test_acknowledged_incident_requires_exactly_one_actor`. Events → `u/test_incident_lifecycle.py::test_acknowledging_records_who_and_writes_the_event`.
- **VIG-20** (OK 3). NOTIFY → `i/test_alert_planning.py::test_the_dispatcher_is_woken_when_the_incident_commits`. Template → `u/test_email_alerts.py::test_the_email_has_zone_severity_value_local_time_and_link`. Mailpit → `i/test_email_dispatch.py::test_the_worker_emails_level_one_and_the_link_confirms_it` (one of the four failures of the first run, section 2.1).

### Sprint 4

- **VIG-21** (OK 2, P 1). Single-use link → `u/test_telegram_link.py::test_opening_the_link_links_the_chat_once`. Token ≤ 64 → no direct assertion on the generated link's length (P). `/start` stores `chat_id` → `i/test_telegram_worker.py::test_opening_the_link_links_the_chat_and_confirms_the_update`.
- **VIG-22** (OK 3, P 1). Button → `i/test_telegram_dispatch.py::test_a_telegram_alert_is_sent_with_its_confirm_button`. `callback_data` ≤ 64 → `len(token) == 43`. `alert_failed` → `test_telegram_failing_twice_delivers_on_the_third_attempt`. Three retries then give up → proved for email only (P).
- **VIG-23** (OK 5). Hash → `u/test_email_alerts.py::test_the_ack_token_has_256_bits_and_only_its_hash_is_kept`. Single use and 24 h → `u/test_confirmation.py::test_a_token_is_single_use_and_lasts_24_hours`. Email → `i/test_confirmation_page.py::test_the_button_confirms_the_incident_as_the_contact_once`. Telegram → `i/test_telegram_confirm.py::test_the_recipient_confirms_with_the_button`. Stops escalation → `i/test_escalation_worker.py::test_acknowledging_stops_the_escalation`.
- **VIG-24** (OK 4). Policy CRUD → `i/test_policies_api.py`. Escalates on `wait_s` → `i/test_escalation_worker.py::test_level_two_is_alerted_when_level_one_expires`. Missing channel → `u/test_alert_planning.py::test_a_target_without_its_channel_is_skipped`. Exhausted → `i/test_escalation_worker.py::test_the_policy_runs_out_after_its_last_level`.

### Sprint 5

- **VIG-25** (OK 6, P 1). Zones by status, stations with value and age → `FE map/live-map-page.spec.ts`, `live-map-presentation.spec.ts`. SSE with JWT in header → `FE realtime/live-events.spec.ts "sends the token in the Authorization header, never in the URL"`. SSE isolation → `i/test_events_api.py::test_each_organization_only_hears_its_own_events_within_two_seconds`. **Update < 2 s** → measured on the server leg only, not rendering (P). Catalog and no-colour distinction → `live-map-presentation.spec.ts`, `ui/visual-states.spec.ts`. New-incident announcement on every page → `FE app.spec.ts`, `incidents/new-incidents.spec.ts`.
- **VIG-26** (OK 5, P 1). Chart and `opened` copy → `FE incidents/readings-chart.spec.ts`, `incident-detail-page.spec.ts`. Timeline, alerts per recipient → `i/test_incident_alerts_api.py`. Email only for admin and operator → `test_each_role_sees_the_alerts_and_only_operator_and_admin_the_email`. `chat_id` never shown → asserted in `i/test_contacts_api.py` but not in the alerts-per-recipient test (P). The detail page's axe test was not confirmed.
- **VIG-33** (OK 6, P 2, NO 1). Single catalog → `ui/visual-states.spec.ts`, no test scans pages for hard-coded status colours (P). No colour alone → same spec (OK). Contrast ≥ 4.5:1 → same spec, both themes (OK). Contrast ≥ 3:1 → measured for map markers only, not UI icons and borders (P). Header per permissions → `FE app.spec.ts` (OK). Shared loading, empty, error → `ui/load-state.spec.ts` (OK). Formats → `ui/formats.spec.ts` (OK). **360 px without horizontal scroll → no test**: jsdom has no layout, the only narrow-screen test checks a CSS class (NO). axe per view → present in all views seen (OK).
- **VIG-34** (OK 6, P 1). List, filters in the URL, SSE reload, aria-live, empty state → `FE incidents/incidents-page.spec.ts`, `inbox-filter.spec.ts`, `new-incidents.spec.ts`; backend `i/test_incidents_api.py::test_the_list_filters_by_status_and_shows_the_newest_first`. "Escalamiento agotado" in red → the text is asserted, the red only indirectly through the tone (P).
- **VIG-35** (OK 5). Buttons per permission, resolve with choice and confirmation, 409 explained, comments 1 to 2000, isolation → `FE incidents/incident-actions.spec.ts`, `incident-comment.spec.ts`; `i/test_incidents_api.py` (`test_each_transition_needs_its_permission`, `test_a_comment_of_exactly_2000_characters_is_accepted`, `test_another_organization_cannot_comment`).

### Sprint 6

- **VIG-36** (OK 6, P 2). Contacts and groups CRUD, permissions, audit, `chat_id` never leaves the API, 409 for a contact with history, 409 naming the policy → `i/test_contacts_api.py`, `i/test_groups_api.py`. Telegram link generation and unlinking → use cases tested, the HTTP endpoints for creating and unlinking the link are not tested directly (P). "Flags contacts without a channel" → dashboard test exists (`contacts-page.spec.ts`), the backend asserts nothing about it (P).
- **VIG-38** (OK 4, P 1). Admin only, cursor pagination, author and before/after, isolation → `i/test_audit_api.py`. Filter by a specific entity id → not obviously covered (P).
- **VIG-39** (OK 4, NO 1). List, header count, reprocess with NOTIFY and audit, reprocessed reading ends evaluated → `i/test_failed_readings_api.py`, `FE failed/failed-readings-page.spec.ts`, `i/test_realtime_triggers.py`. Runbook uses the dashboard → documentation only (NO).
- **VIG-27** (OK 5, P 1). REST CRUD with params validated per type, audit, permissions, preview → `i/test_rules_api.py`, `i/test_rule_preview_api.py`. Forms per type → only the threshold and silence forms are tested in `FE rules/rules-page.spec.ts`, **not rate-of-change** (P).

### Sprint 7

- **VIG-28** (OK 2). `received_to_alert_seconds` → implemented as a JSON log field, an SQL function and `make latency`, not as a scrapeable metric; tested in `u/test_email_alerts.py`, `u/test_latency.py`, `i/test_email_dispatch.py` (one of the four failures of the first run, section 2.1). `correlation_id` end to end → `u/test_ingestion.py`, `u/test_process_batch.py`, `i/test_email_dispatch.py`.
- **VIG-29** (OK 3). 50 stations × 30 min, zero unevaluated after 120 s, p95 < 30 s → `make loadtest`; its plan, verdict and counting query are tested (`u/test_load_plan.py`, `u/test_latency.py`, `i/test_load_test.py`), and the 30-minute run itself is manual, not in CI. Runs:
  - **Machine B, 2026-10-03, 20 CPUs, before the cache:** 9,000 batches, 0 rejected, 0 unevaluated, p95 0.50 s. Recorded in `docs/sprints/sprint-7.md`, which the first pass of this audit missed.
  - **Machine A, before the cache, two runs:** 1,066 and 2,745 of 9,000 batches failed at the client (`ReadTimeout`, 10 s). SPEC's two numbers still held: 0 unevaluated, p95 about 1 s.
  - **Cause, measured on machine A:** every batch verified its API key with Argon2id, about 133 ms of CPU, with no memory of earlier checks. `POST /v1/readings` took 136 ms alone; 50 at once took a median of 4.4 s and at most 6.6 s, about 50 × 133 ms queued on 4 CPUs.
  - **Fix (commit `b624e97`):** the API process remembers successful verifications (VIG-08 above). On machine A, 50 requests at once then took a median of 1.3 s and at most 1.4 s.
  - **Machine A, after the fix:** 16 of 9,000 batches failed (0.18 %), all at one instant (10 `ReadTimeout` and 6 `ReadError`); 0 unevaluated, p95 1.3 s. The tool reports FAIL because it requires 0 rejected. The API and Postgres logs show no error or restart; the cause was not identified.
  - **Machine B, after the fix, its Docker limited to 4 CPUs and 3.83 GiB (2026-10-12, 21:13 to 21:45 Lima time):** 9,000 batches, **0 rejected**, 0 unevaluated, 50 incidents, p50 0.10 s, **p95 0.17 s**, max 0.20 s: PASS. Not a clean run: two other projects (one running k6 load tests) and three testcontainers runs shared that Docker. Willay's API peaked at 35 % of one CPU and Postgres at 25 %, and Docker recorded no restart, OOM or unhealthy Willay container. Argon2id is about 2.5 times faster per core on machine B (52 ms against 133 ms), so this run does not replicate machine A.

  The 16-batch stall did not recur. It stays an isolated event with no proven cause.
- **VIG-30** (P 2). `make demo` reaches both incidents acknowledged at level 2 → the story logic is unit-tested (`u/test_demo_story.py`, `u/test_demo_mailbox.py`, `i/test_demo.py`), the full run is not in CI and I did not run it (P). README with video and screenshots → screenshots present, **no video link** (P).
- **VIG-40** (OK 3, P 1, NO 1). Missing key fails a test → `FE i18n/translations.spec.ts`, `u/test_i18n.py` (OK). Nothing hard-coded → no lint rule or test (NO). Dashboard language → `FE i18n/language.spec.ts`, `i/test_identity_api.py` (OK). Contact language → the confirmation page is tested, email and Telegram language was not confirmed (P). API errors with `code` → `u/test_api_errors.py` (OK).
- **VIG-41** (OK 4, P 3, NO 1). Follows the system → `FE theme/theme.spec.ts` (OK). Kept in the browser → same (OK). Applied before load → the script's logic is tested, not the absence of a flash (P). Semantic colours, never a fixed gray → no scan (P). Dark shade per state, same contrast tests → `ui/visual-states.spec.ts` (OK). Switching redraws nothing → no test types in a form and switches (P). **Dark base map → no test** (NO). Confirmation page follows the system mode → `i/test_confirmation_page.py` (OK).

### Sprint 8

- **VIG-42** (P 2, NO 4). Compose prod behind Caddy → only `docker compose config --quiet` (P). `config.json` at container start → entrypoint untested (P). Keycloak admin console unreachable → configured, untested (NO). `make secrets` → untested (NO). Runbook → exists, documentation (NO). arm64 and amd64 → claimed in ADR-0010, no multi-arch check (NO).
- **VIG-43** (OK 5, NO 3). Off unless demo mode → `i/test_demo_api.py::test_the_demo_is_off_unless_the_server_turns_it_on`. Run button, one at a time, progress → `i/test_demo_api.py`. Plays the scenario, keeps stations reporting, nightly restore → `i/test_demo_worker.py`, `u/test_demo_live.py`. Demo accounts and guide on the sign-in screen → no test (NO). Accounts cannot change their password → Caddy rule, no test (NO). Link to Mailpit → Caddy route, no test (NO). `test_a_playing_scenario_says_where_the_story_is` failed in the first run (section 2.1).
- **VIG-44** (OK 5, P 2). GET for all roles, PUT admin only, audited, language, IANA zone → `i/test_organization_api.py`, `u/test_organization.py`. Default language for contacts without one → no test shows a message sent in the organization's language when `contacts.language` is null (P). "Used by messages" → no test shows that changing the organization time zone changes an email (P).
- **VIG-37** (OK 4, NO 1). Levels, minutes, groups per channel, field errors, 409 for a policy in use → `FE contacts/policies-page.spec.ts`, `i/test_policies_api.py`. Notice that changes also apply to ongoing incidents → no test found by name (NO).
- **VIG-31, VIG-32, VIG-45:** no verificado.

### Totals for section 3

198 criteria examined (VIG-06, 07, 31, 32 and 45 excluded): **149 OK · 33 partial · 16 without a test.** Backend and infra: 105 / 23 / 12. Dashboard: 44 / 10 / 4.

---

## 4. Data

SPEC "Database schema" and "Database roles" against `backend/migrations/versions/0001` to `0014` and `infra/postgres/init/01-init.sh`.

| Item | Status | Evidence |
| --- | --- | --- |
| 17 `core` tables and 4 `ingest` tables | Cumple | 0002 creates 16 `core` tables, 0014 adds `demo_runs`, 0003 creates the 4 `ingest` tables. `i/test_schema.py::test_all_tables_exist`. |
| Columns, PKs, FKs, unique and CHECK constraints | Cumple | Compared table by table, nothing from the spec is missing. Examples: `incidents` partial unique index on `dedup_key` (`0002:261`) and ack-by CHECK (`0002:245-253`); `incident_events` event-type CHECK with the same 11 values; `alerts (status, next_attempt_at)` index. |
| `readings` hypertable (1-day chunks, compression after 7 d, retention 180 d) | Cumple | `0003:39-51`; `i/test_schema.py::test_readings_is_a_hypertable_with_columnstore_and_retention`. |
| Roles, `keycloak` database, extensions | Cumple | `01-init.sh:17-31`; migration 0001 only runs `CREATE EXTENSION IF NOT EXISTS` as a check (`0001:26-27`), as ADR-0005 says. |
| `ALTER DEFAULT PRIVILEGES` in both schemas | Cumple | `0001:36-39`; `i/test_db_privileges.py::test_table_created_later_by_owner_is_granted_to_app`. |
| REVOKE on append-only tables | Cumple | `0002:329-331` (UPDATE, DELETE, TRUNCATE); tested. |
| `NOTIFY willay_events` triggers | Cumple | `0008`, `0009`; payload carries organization and type only. |
| Direct test of the init script (roles, extensions) | Parcial | Only exercised indirectly. |
| SPEC schema tables are current | Cumple | The migrations add objects the SPEC tables do not list: `correlation_id` (`evaluation_queue`, `incidents`), `trigger_received_at`, `incident_events_one_recovery` unique index, `alerts.destination` nullable with a CHECK, `lower(email)` unique index on `users`, extra CHECKs and indexes, an FK from `evaluation_queue` to `core.stations`. Additive and documented in migration docstrings, but SPEC and the ADRs were not updated. **Update, 2026-10-13:** SPEC's tables now list them. |

Section 4: 8 Cumple · 1 Parcial · 0 No cumple.

---

## 5. Decisions (ADRs)

All ten ADRs exist (`docs/adr/0001` to `0010`, plus an index). **Every one has status "Proposed"**, including 0001 to 0004, although the code is built on them; the ADR README defines the Proposed → Accepted step and none was promoted. **Update, 2026-10-13:** all ten are now Accepted.

| ADR | Status | Matches the code? |
| --- | --- | --- |
| 0001 single backend | Cumple | Layout and processes match. It said five workers; corrected to six (`demo`) on 2026-10-13. |
| 0002 Postgres as queue | Cumple | `pg_queue.py:16-47` matches. Its "Poison rows" point and its criteria for migrating were there all along: the first pass searched for "poison" in lower case and missed them. Since 2026-10-13 it says failed rows are reprocessed from the dashboard (VIG-39). |
| 0003 TimescaleDB | Cumple | Chunk, columnstore and retention settings match; TSL license and no-RDS constraint are written (lines 36-37). |
| 0004 Keycloak organizations | Cumple | `principal.py:63-81` parses the object, rejects zero or several, resolves by id. 403 mapping not read. |
| 0005 init script | Cumple | Matches `01-init.sh`. |
| 0006 SQL migrations | Cumple | Migrations are raw `op.execute` SQL; `env.py:35` uses `transaction_per_migration=True`. Testcontainers fixtures not checked. |
| 0007 triggers for live events | Cumple | Matches `0008`, `0009`. |
| 0008 i18next | Cumple | `i18next` pinned, `i18n/i18n.ts`, `translations.spec.ts`. |
| 0009 light and dark with CSS variables | Cumple | `@custom-variant dark` and `:root.dark` in `styles.css`. |
| 0010 deploy behind Caddy | No verificado | Files exist; routing and `!reset` port removal not checked. |

Section 5: 9 Cumple · 0 Parcial · 1 No verificado.

---

## 6. Deviations from SPEC.md

| # | Deviation | ADR justifies it? | Status |
| --- | --- | --- | --- |
| 1 | Alembic used only as a runner with raw SQL, no autogenerate | Yes, ADR-0006 | Cumple |
| 2 | A sixth worker, `demo` (off unless `WILLAY_DEMO_MODE`) | No ADR for it; SPEC documents VIG-43 and `demo_runs`, but ADR-0001 and SPEC's "five workers" are stale | Cumple (SPEC and ADR-0001 updated on 2026-10-13) |
| 3 | Schema objects beyond the SPEC tables (section 4) | No; migration docstrings only | Cumple (SPEC and ADR-0001 updated on 2026-10-13) |
| 4 | Packages `demo`, `loadtest`, `seed` outside the four-layer scheme and missing from the SPEC tree | No | Cumple (SPEC and ADR-0001 updated on 2026-10-13) |
| 5 | `application` layers import SQLAlchemy's `AsyncConnection` (9 files: `alerts/application/{escalation,planning,telegram_bot}.py`, `incidents/application/{open_incident,station_recovery}.py`, `rules/application/{evaluate,queue,rule_evaluator,silence_check}.py`). CLAUDE.md forbids it only in the domain | No | Parcial |
| 6 | `received_to_alert_seconds` is a log field, an SQL function and a CLI, not a metric | No | Parcial |
| 7 | CI runs the underlying commands, not `make lint` and `make test`; OpenAPI freshness is a pytest test, not a CI step | No (SPEC says "CI fails if not up to date", which the test satisfies) | Parcial |
| 8 | OpenAPI contract is guarded | n/a, `u/test_openapi_contract.py` | Cumple |
| 9 | README without the video VIG-30 requires | No | No cumple |
| 10 | All ADRs "Proposed" after implementation | Resolved: all Accepted on 2026-10-13 | Cumple |
| 11 | No `shared/tenancy` (lives in identity) | No | Cumple (SPEC and ADR-0001 updated on 2026-10-13) |

Section 6: 7 Cumple · 3 Parcial · 1 No cumple.

Stack versions: Python `>=3.12,<3.13`, Node `^24.15.0` (README and `.nvmrc` agree), Angular 22.2, TypeScript ~6.0, Keycloak 26.7.4, `timescale/timescaledb-ha:pg16-ts2.30`. I did not check against the vendors' release calendars that Angular 22 and the others are still supported today; the SPEC asks for that review in sprint 0 and I found no record of it.

---

## 7. Scalability risks

| # | Finding | Status |
| --- | --- | --- |
| 1 | **API reaches into another module's infrastructure** (3 imports): `territory/api/stations.py:13-14` imports `ingestion.api.dependencies` and `ingestion.infrastructure.api_keys`; `alerts/api/confirm_page.py:17` imports `incidents.infrastructure.incidents_repository.SqlIncidentRepository`. | No cumple |
| 2 | **Application-layer cycle `rules` ↔ `alerts`**: `rules/application/{rule_evaluator,silence_check}.py` import `alerts.application.planning`; `alerts/application/{escalation,telegram_bot}.py` import `rules.application.evaluate.Transaction`. `incidents` is the hub, `rules` the orchestrator. It works because they import distinct submodules. | No cumple |
| 3 | `Transaction` protocol lives in `rules` and is borrowed by `alerts`; it belongs in `shared`. | Parcial |
| 4 | Infrastructure importing another module's application or domain: `rules/infrastructure/sql_silence.py:6` (incidents application), `rules/domain/rules.py:12` and `rules/infrastructure/rules_repository.py:11` (`incidents.domain.severity`), `alerts/infrastructure/sql_confirmation.py:15`. | Parcial |
| 5 | 11 API files import `identity.api.dependencies.require`. Acceptable as a shared dependency, but it couples every module's API to identity's API layer. | Parcial |
| 6 | Biggest dashboard unit: `rules/rules-page.ts` (398 lines) and its 366-line template. | Parcial |
| 7 | File size: largest tracked Python file 395 lines (a test); largest source file 393 (`demo/__main__.py`); none over 400. | Cumple |
| 8 | Class size: largest are `SqlStationRepository` (149 lines), `DemoWorker` (136), `TelegramPoller` (93). | Cumple |
| 9 | Code duplicated between modules | No verificado (no systematic scan; repositories in territory, alerts and incidents have a similar shape but were not diffed) |

Section 7: 2 Cumple · 4 Parcial · 2 No cumple · 1 No verificado.

---

## 8. Reproducibility

| Item | Status | Evidence |
| --- | --- | --- |
| `make up` on this working tree | Cumple | I ran it: all 12 containers reached healthy and `migrate` exited 0. This tree already had a `.env` and no containers or volumes. On machine B the first `make up` failed: a Postgres container from 2026-10-02 had lost its network when Compose recreated the network, so `migrate` could not resolve `postgres`. `make down` and `make up` fixed it: an old container, not a defect of the repository. |
| `make seed` | Cumple | I ran it: 2 organizations seeded, 10 API keys printed and saved to `.secrets/station-keys.json`. |
| From a fresh `git clone` with the documented command | No verificado | Not executed. The Makefile creates `.env` from `.env.example` (`Makefile:33-36`) and the CI `compose` job starts from a clean runner (`docker compose up --wait`, migrate exit 0, seed and simulator smoke test), but I did not run that path. |
| Local `make lint` / `make test` for the dashboard | Cumple | They need Node `^24.15.0`, as the README says. Machine A has 22.16, so the commands behind them ran on machine B in a `node:24` container (Node 24.21): lint clean, 331 tests passed, build complete. |
| `make loadtest` | Cumple | Ran on both machines; results in section 3, VIG-29. |
| `make demo`, production deploy | No verificado | Not executed. |

Section 8: 4 Cumple · 0 Parcial · 0 No cumple · 2 No verificado.

---

## Summary

| Section | Cumple | Parcial | No cumple | No verificado |
| --- | ---: | ---: | ---: | ---: |
| 1. Structure | 5 | 1 | 0 | 0 |
| 2. Architecture rules | 18 | 2 | 1 | 2 |
| 3. Acceptance criteria (OK / partial / no test) | 149 | 33 | 16 | 5 stories |
| 4. Data | 8 | 1 | 0 | 0 |
| 5. ADRs | 9 | 0 | 0 | 1 |
| 6. Deviations | 7 | 3 | 1 | 0 |
| 7. Scalability | 2 | 4 | 2 | 1 |
| 8. Reproducibility | 4 | 0 | 0 | 2 |

---

## Corrections, by priority

### Blocking

1. **Resolved: the four failing integration tests** (section 2.1). With nothing else on Docker the suite passed 977/977, and 982/982 with the API key cache; the four failed only while another project competed for the same resources. One run each way, so keep an eye on CI.
2. **Two Must stories have an explicit criterion with no evidence:** VIG-33 "usable at 360 px without horizontal scrolling" (needs a real-browser test; jsdom has no layout) and VIG-30 "README with video" (no video link).
3. **Resolved: VIG-29 evidence** (section 3). The 30-minute run passed on machine B with its Docker limited like machine A's (0 rejected, p95 0.17 s), and the cause of machine A's client timeouts, an uncached Argon2id check per batch, was fixed. The 16-batch stall seen once on machine A did not recur and has no proven cause.

### Important

4. Add architecture tests (import-linter or an AST test) for: domain imports no FastAPI or SQLAlchemy; no API layer imports another module's infrastructure; no workers in the lifespan.
5. Remove the layering violations in section 7: the three API → other-infrastructure imports, the `rules` ↔ `alerts` cycle (move `Transaction` to `shared`).
6. Test the untested parts of VIG-42 and VIG-43: Keycloak admin console unreachable, `make secrets`, demo accounts unable to change their password, the Mailpit route, multi-arch images.
7. Missing tests: VIG-37 "applies to ongoing incidents" notice, VIG-40 "no hard-coded strings" (an ESLint rule for templates would do), VIG-27 rate-of-change form, VIG-41 dark base map and form-survives-theme-switch, VIG-44 default language and time zone reaching an email.
8. **Done on 2026-10-13:** the ADRs are Accepted, ADR-0001 says six workers and ADR-0002 sends failed rows to the dashboard. Still open: decide whether `demo`, the extra schema objects and the API key cache (VIG-29) deserve an ADR.
9. **SPEC done on 2026-10-13:** schema tables (section 4), repository tree (demo, loadtest, seed, `tests/support`) and the demo worker. Still open: the two missing runbooks (rotate API keys, restore the DB).
10. Create `docs/BACKLOG.md` and `docs/ARCHITECTURE_RULES.md`, or drop them from the audit brief, so the references stop dangling.
11. Verify a fresh-clone `make up` once and record it (section 8).

### Minor

12. CI should call `make lint` and `make test` (or the Makefile and CI should be declared equivalent).
13. Small assertion gaps: VIG-04 one-level isolation policy, VIG-21 link length, VIG-22 give-up after retries for Telegram, VIG-17 15 s interval, VIG-38 filter by entity id, VIG-26 `chat_id` absent from alerts-per-recipient, VIG-34 the red tone.
14. Split `rules/rules-page.ts` (398 lines plus a 366-line template) before it grows.
15. Check Angular, Node, Postgres and Keycloak against their support calendars and record it.
16. Audit VIG-06, VIG-07, VIG-31, VIG-32 and VIG-45, which this audit did not cover.
