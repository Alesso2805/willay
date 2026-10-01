# Sprint 3 — Silence detected, incidents without duplicates and first email (VIG-17 to VIG-20)

**Status as of 2026-09-29:** the 4 stories (16 points) are done, merged into `main` with green CI and verified against the real stack. The plan placed them between November 9 and 22, so we are still ahead of schedule.

## What was delivered

| Story | PR | Result | Verification on the real stack |
| --- | --- | --- | --- |
| VIG-17 | #8 | `silence` worker every 15 s: one incident per silent station, `station_recovered` only once (migration 0005) and rate limit purge | RIM-SEU-01 opened its incident 35.4 s after its last heartbeat (limit: 60 s); the 3 stations of a zone rule opened one each; RIM-003, which never reported, did not alert |
| VIG-18 | #9 | Cooldown for every rule type, `reading_added` only if the reading worsens the incident, race between two evaluators | A resolved silence did not reopen during the cooldown; the RIM-CHA-01 drop incident recorded only its new minimums |
| VIG-19 | #10 | Incidents API: list, detail with timeline, acknowledge (responder and above) and resolve (operator and above); 409 on invalid transitions | With a real Keycloak token: acknowledge, resolve without acknowledging, and 409 on repeating |
| VIG-20 | #11 | Level 1 alerts when an incident opens and an email `dispatcher` worker with retries, local time and a confirmation link (migration 0006) | The email reached Mailpit 0.04 s after the reading was received (p95 target: 30 s) |

## Sprint decisions

- **Silence:** a station that never reported does not count as silent, and `station_recovered` is recorded by the `silence` worker, not by ingestion.
- **Uniqueness in the database:** "only once" (active incident, recovery) is guaranteed by a partial unique index, not by a racy "insert if not exists".
- **`reading_added`:** only the readings that worsen the trigger value get in; reprocessing a reading does not duplicate events.
- **Lifecycle:** an open incident can be resolved without acknowledging it first; `resolved` is final.
- **Email:** plain text with the organization's local time; retries after 5, 10 and 20 s; the timeline never stores the email address or the `chat_id`.
- **Confirmation:** the link opens an API page without login with a button (POST). Opening it never confirms, because email scanners open links on their own.

## Picking it up again

```bash
git switch main
make up && make seed
make lint test
make simulate ARGS="--scenario rimac --seed 42"   # drop on RIM-CHA-01 and, 4 min later, silence on RIM-SEU-01
```

The alert emails can be seen in Mailpit: http://localhost:8025.

## Changes to SPEC.md and CLAUDE.md in this sprint

- `c753099` docs(spec): silence ignores stations that never reported (PR #8)
- `23c3f5a` docs(spec): reading_added only when the trigger value worsens (PR #9)
- `7c531e3` docs(spec): an open incident can be resolved without acknowledging (PR #10)
- `db11f26` docs(spec): email content, retry timing and a confirmation page (PR #11)

## To do

- [ ] The confirmation link in the emails answers 404 until VIG-23, which brings the page and the POST.
- [ ] Telegram alerts are created but stay pending until VIG-22.
- [ ] A level with no deliveries at all must escalate immediately (VIG-24).
- [ ] Decide with VIG-23/24 whether a pending alert is still sent when the incident has already been acknowledged.
- [ ] From previous sprints: accept ADRs 0001–0006; show the organization's name in `/v1/me` and in the dashboard; Node 24 in WSL and move the repo to the WSL file system; decide whether to delete `refs/backup/*` and the local branches `feat/VIG-01` to `feat/VIG-11`.

## Retro

- **Went well:** asking the product decisions before each story, with a recommended option, kept the pace. The live tests found a real gap (a resolved silence reopened) that VIG-18 closed, and two poorly worded texts.
- **To improve:** in VIG-18 I promised three commits but split them at the end, rebuilding an intermediate state. Each part has to be committed as soon as its tests pass.
- **To try:** in Sprint 4, besides the mutations, record the equivalent mutants, such as the tenant filter one that the request rollback neutralizes. They document defenses in depth that no test can see.
