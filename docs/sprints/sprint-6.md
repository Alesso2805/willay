# Sprint 6 — Management from the dashboard: contacts, failed readings, rules and audit (VIG-36, 39, 27, 38)

**Status as of 2026-10-02:** the 4 stories (22 points) are done, merged into `main` with green CI and checked against the real stack with real users; the product owner reviewed rules and audit in the browser. The plan placed them between December 21 and January 3. Order: VIG-36, 39, 27, then 38. The suites ended up at 755 backend tests and 210 dashboard tests.

## What was delivered

| Story | PRs | Result | Verification on the real stack |
| --- | --- | --- | --- |
| VIG-36 | #40, #41, #42, #43 | Contacts and groups: admin manages, operator reads; a contact with history gets 409 and is removed from its groups instead; a group a policy notifies gets 409 naming the policy; the Telegram link is shown once, with its expiry; contacts without a channel and groups without members or policy are flagged. Contactos and Grupos are two tabs of one section | A throwaway contact and group were created, linked, edited and deleted as admin; the operator saw them read-only at 360 px; the viewer got an explanation instead of a 403 |
| VIG-39 | #44, #45 | Failed readings: a page that lists and reprocesses them (operator and admin, new `readings:reprocess` permission), a notice on every page while there is any, and the runbook moved to the dashboard. A trigger (migration 0009) announces them live | A reading that failed showed the notice on another page ~400 ms later; reprocessing emptied the list and the notice and the real evaluator evaluated it |
| VIG-27 | #46, #47, #48 | Rules: an API with params validated per type with the evaluator's own functions, a 24 h preview that marks where a draft would have opened an incident, and a page with forms per type | The preview found this morning's real RIM-CHA-01 drop; the product owner created, edited (type locked) and deactivated a rule, and saw it in the audit log |
| VIG-38 | #49, #50 | Audit log for admin: who changed what, each field before and after in words, filters by type, author and dates in the URL, cursor pagination that neither repeats nor skips rows | 33 entries in pages of 7 with no repeats; the product owner's review found an inverted date range answered by a generic error and an entry named by its id, both fixed before merging |

Also merged during the sprint:
- **#51**, a real race in the escalation worker (VIG-24) seen once in CI: a worker could escalate an incident a second time when another one had just escalated it, because the subqueries of a `SELECT … FOR UPDATE` kept the old snapshot. The lock and the read are now two statements.
- **#52**, found while taking this sprint's screenshots: opening the audit log from a shared URL filtered the list, but its selects showed "Todo" and "Cualquiera", because a `<select>`'s value was set before its options existed.
- The dashboard's initial bundle warning moved from 500 kB to 550 kB (#50, its own commit); transferred it is about 123 kB.

## Sprint decisions

- **Contacts:** deleting one with history (alerts or acknowledgements) returns 409 with no side effect; removing it from its groups is a separate, audited action. Linking a contact to a platform user (`contacts.user_id`) stays out of scope.
- **Groups:** the zone is a label for the admin, alerting does not use it; the member list is sent whole on every edit.
- **Failed readings:** announced live by a trigger on `failed_at`, like incidents and heartbeats (ADR-0007); reprocessing is audited once per station with each measurement and its error; the page has no menu item: it is reached from the notice, which only shows while there is something to do.
- **Rules:** the type never changes after creation; DELETE deactivates (incidents point to the rule); edits apply from the next reading; threshold and rate-of-change rules name their station and only silence covers a whole zone, so a rule never compares different units.
- **Preview:** it marks the start of each episode in which the draft would have opened an incident, with the evaluator's own functions; it does not simulate the cooldown, which depends on when someone resolves.
- **Audit:** admin only; the read side lives in the `identity` module (who did what); the entity filter works by URL, without "Historial" links on the other screens.

## Picking it up again

```bash
git switch main
make up && make seed
make lint test
make simulate ARGS="--scenario rimac --seed 42"
```

The dashboard is at http://localhost:4200 (users `rimac-operator`, `rimac-responder`, `rimac-viewer`, `rimac-admin`, with `WILLAY_DEV_USER_PASSWORD` from `.env`) and the emails at http://localhost:8025. A database from before this sprint needs the migrate container to reach migration 0009 (`make migrate`).

## Changes to the specification in this sprint

- `ac4e6b7` docs(spec): failed readings also notify the dashboard live (VIG-39)
- `8a76245` docs(spec): only silence rules may cover a whole zone (VIG-27)

## To do

- [ ] **Relink Telegram** after the rename: no contact has a chat, so every Telegram alert is skipped.
- [ ] **Accept ADRs 0001–0007** (0007, live events from triggers, now also covers failed readings).
- [ ] **Ports:** the other local project (`keycloak_custom` on 8080 and `pgsql_keycloak` on 5433) still clashes with Willay.
- [ ] **VIG-30:** `make demo` must reset the demo data (the 30 min cooldown prevents repeating the scenario right away).
- [ ] **Visibility:** a worker without `LISTEN` still keeps a green healthcheck (it polls).
- [ ] **Review the same lock pattern elsewhere:** contacts, groups and rules also read subqueries in a `SELECT … FOR UPDATE`; there a stale value only affects an audit "before" or a check the database also enforces, but it is worth the same two-statement form.
- [ ] The rule the product owner created while reviewing ("Baja más de 9999 mm" on RIM-CHO-02) is deactivated in the local database; remove it if it gets in the way.
- [ ] Delete the local branches `feat/VIG-01` to `feat/VIG-11` and `refs/backup/*`.

## Retro

- **Went well:** the tests caught real bugs before anyone saw them: a disabled control missing from Angular's `valueChanges`, `reset()` emptying the form's defaults, a silence preview breaking on a station that never reported, and a race in the escalation worker that CI exposed once. The product owner's review in the browser found what the tests had not: an inverted date range answered by a generic error.
- **To improve:** the stacked PRs (up to 6 deep) made every merge a rebase per PR and pushed unrelated stories on top of each other only to keep the local stack complete; a flaky test held a merge until its cause was understood.
- **To try:** in Sprint 7, stack only what truly depends on the previous PR, and run the dashboard against a URL with every filter set (as a shared link would) before calling a screen done.
