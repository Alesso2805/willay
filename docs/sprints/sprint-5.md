# Sprint 5 — Accessible live dashboard: map, inbox and incident detail with their actions (VIG-33, 25, 34, 26, 35)

**Status as of 2026-10-02:** the 5 stories (24 points) are done, merged into `main` with green CI and checked against the real stack with real users. The plan placed them between December 7 and 20. Order: VIG-33 first (the rest is built on its visual catalog), then 25, 34, 26 and 35. The suites ended up at 617 backend tests and 145 dashboard tests.

## What was delivered

| Story | PRs | Result | Verification on the real stack |
| --- | --- | --- | --- |
| VIG-33 | #20 | Single catalog of visual states (color, icon and text) with contrast tests, navigation by permission, loading/empty/error states with one component, common formats, axe-core in every view's tests, the "monitoring center" look | The product owner rejected the first look and approved the redesign in the browser |
| VIG-25 | #21, #28, #29, #30, #33 | Live channel: database triggers → `LISTEN` → SSE per organization, the JWT in the header via `eventsource`. "Mapa en vivo" with zones by their most urgent incident and stations by state, with an incident badge. A new incident is announced on every page | A reading reached the screen in 159–177 ms and a new-incident notice in 166–237 ms; stopping the API showed "Sin conexión en vivo" and starting it brought "En vivo" back in 3.2 s; acknowledging from the email now shows on the station's marker |
| VIG-34 | #32 | Incident inbox, newest first, with status and severity filters kept in the URL (the API filters severity too) | 6 active incidents; the severity filter answered by the API (5 warning, 1 critical); no horizontal scroll at 360 px |
| VIG-26 | #34, #35, #36 | Incident detail: timeline in words with who acted, alerts by recipient as a table (the email only for operator and admin, the `chat_id` never), readings chart drawn as plain SVG with the `opened` evidence as fallback | `rimac-operator` saw 4 emails and `rimac-viewer` none on the same 7 alerts; RIM-CHA-02's minute of readings, the silence and the opening read clearly, also at 360 px |
| VIG-35 | #37 | Acknowledge, resolve (resolved or false alarm, in a panel inside the card) and comment from the detail, by permission; a 409 is explained and the incident reloaded | Three real users on a new incident: the viewer saw the acknowledgement, the comment and the false alarm 216–257 ms after each one |

Also merged during the sprint: the codebase and documentation in English (#22–#25), the product name **Willay** and the rename of everything from `vigia` (#26, #27), `make` from PowerShell and Git Bash on Windows (#31), and the workers' `LISTEN` reconnecting after a database restart (#38, found while checking VIG-35).

## Sprint decisions

- **Live channel:** the server closes the stream when the token expires and the client reconnects; a gap under 5 s still counts as live. While it is down the dashboard says so on every screen, reloads every 15 s, and judges silence by its newest data, not by the clock.
- **Map:** a zone takes the state of its most urgent active incident, so acknowledging one incident may not change it; that is why each station's marker carries a badge with its own incident's state and the zone's tooltip counts incidents by state. A station without a zone is shown as such even if it reports.
- **New incidents** are announced on every page until closed, in an assertive live region that is always in the page; if the incident cannot be fetched, it is announced without details.
- **Inbox:** filters in the URL with the API's values; at least one status stays checked; the API filters severity so the limit applies to matching incidents.
- **Detail:** the alerts span the page as a table (cards on a phone); the chart is plain SVG with no library, drawn at its real width, its time axis fitted to the readings and the marks, with a summary in words and "Ver como tabla".
- **Actions:** resolving asks how it ended in a panel inside the card (not a modal), and it is final; comments are allowed on resolved incidents.
- **Product and code:** the product is called Willay; code, comments and docs are in English, user-facing text stays in Spanish until VIG-40.

## Picking it up again

```bash
git switch main
make up && make seed
make lint test
make simulate ARGS="--scenario rimac --seed 42"
```

The dashboard is at http://localhost:4200 (users `rimac-operator`, `rimac-responder`, `rimac-viewer`, `rimac-admin`, with `WILLAY_DEV_USER_PASSWORD` from `.env`) and the emails at http://localhost:8025. `make` now works from PowerShell and Git Bash as well as WSL.

## Changes to SPEC.md and CLAUDE.md in this sprint

- `52443ee` docs(spec): validation interviews postponed past the MVP (PR #19)
- `44cabe0` docs(spec): accessibility checked with axe-core in CI instead of Lighthouse (PR #20)
- `f5f02f8` docs(spec): SSE client eventsource instead of the unmaintained fetch-event-source (PR #21)
- `1c968db` docs(spec): live events come from triggers, with ready, resync and token expiry (PR #21)
- `ef0c1b9` docs(spec): SPEC in English; user-facing text stays Spanish until i18n (PR #24)
- `1b824d7` docs(spec): add VIG-40, bilingual product (PR #24)
- `0f9d0d3` docs(spec): product name Willay (PR #26)
- `e44ce32` docs(spec): everything is renamed to willay; story IDs keep VIG- (PR #27)
- `a3dde20` docs(spec): the dashboard says when it is not live and reloads every 15 s (PR #28)
- `1227b13` docs(spec): while offline the dashboard judges silence by its newest data (PR #28)
- `d59a3c4` docs(spec): a zone on the live map takes its most urgent incident's status (PR #29)
- `8adfb35` docs(spec): new incidents are announced on every page (PR #30)
- `e7a6e9c` docs(spec): station markers carry their incident's status (PR #33)
- `c384576` docs(spec): what the incident's readings chart shows (PR #36)

## To do

- [ ] **Relink Telegram** after the rename: no contact has a chat in the new database, so every Telegram alert is skipped ("el contacto no vinculó Telegram").
- [ ] **Accept ADRs 0001–0007** (0007, live events from triggers, is still Proposed).
- [ ] **Ports:** the other local project (`keycloak_custom` on 8080 and `pgsql_keycloak` on 5433) still clashes with Willay.
- [ ] **VIG-30:** `make demo` must reset the demo data (the 30 min cooldown prevents repeating the scenario right away).
- [ ] **Watch:** once, `docker compose up -d --build dashboard` recreated the Postgres container (clean shutdown, data kept); the cause was not found because Docker Desktop keeps no event history.
- [ ] **Visibility:** a worker without `LISTEN` still keeps a green healthcheck (it polls); #38 retries and logs it, but consider showing it in the healthcheck.
- [ ] Delete the local branches `feat/VIG-01` to `feat/VIG-11` and `refs/backup/*`.

## Retro

- **Went well:** checking each screen in the browser with real users and the product owner's own data found what the tests could not: an unreadable chart on a phone, a sliver of readings on a fixed 3-hour axis, a narrow alerts column, a map that did not show an acknowledgement, and workers that stopped listening after a restart.
- **To improve:** some screens were designed for ideal data (a station reporting for hours) instead of the demo's (a minute of readings, nothing linked to Telegram); design every screen against the real demo data first.
- **To try:** in Sprint 6, before coding each screen, answer "after the operator acts, where on this screen do they see it happened?"
