# Sprint 1 — Authenticated readings are enqueued atomically per tenant (VIG-06 to VIG-11)

**Status as of 2026-09-29:** all 6 stories done and verified against the real stack, ahead of the planned dates (Oct 12–25). CI on GitHub still does not run: there is no remote.

## What was delivered

| Story | Result | Verification on the real stack |
| --- | --- | --- |
| VIG-06 | OIDC login (Code + PKCE, `organization:*` scope), `CurrentPrincipal`, `GET /v1/me`, 403 with zero or several organizations | Browser login with `rimac-operator`; 403 for `sin-org` and `dos-orgs` |
| VIG-07 | Permission matrix (SPEC › Permissions by role) and `require(Permission)` | `/v1/me` returns each role's permissions with Keycloak tokens |
| VIG-08 | `POST /v1/readings` with `X-Api-Key`, batches of 1 to 500, 60 batches/min per station | 70 concurrent batches on 2 replicas: 60 accepted and 10 with 429 |
| VIG-09 | Late readings (> 1 h) stored without being enqueued; `NOTIFY` to the evaluator only after commit | `LISTEN` receives the notification; `"late": 1` in the response |
| VIG-10 | Heartbeat in `station_heartbeats` with `last_measured_at` (migration 0004); it never goes backwards | Heartbeat with the most recent on-time value, ignoring the late one |
| VIG-11 | `make simulate` with the normal/rise/drop/silence/rimac scenarios, reproducible with a seed | `rimac` scenario against the API: drop from 85 to 33 m³/s at the event step |

## Changes to the specification in this sprint

- `6eb3d39` docs(spec): role permission matrix
- `8062938` docs(spec): add last_measured_at to station heartbeats
- `f06a80b` docs(spec): use httpx2 as the HTTP client

## Retro

- **Went well:** testing against the real stack and with mutations found bugs that the green tests did not show: a 500 with `NaN`, a Keycloak without a port and an SQL syntax error.
- **To try:** in Sprint 2, open the remote and one PR per story, so that CI validates each delivery.
