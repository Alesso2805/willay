# Sprint 4 — Telegram linked, confirmation and automatic escalation (VIG-21 to VIG-24)

**Status as of 2026-09-30:** the 4 stories (16 points) are done, merged into `main` with green CI and verified against the real stack, with a real Telegram bot. The plan placed them between November 23 and December 6. Chosen order: VIG-23 → 24 → 21 → 22, to test confirmation and escalation by email before adding Telegram. The suite ended up at 572 tests.

## What was delivered

| Story | PR | Result | Verification on the real stack |
| --- | --- | --- | --- |
| VIG-23 | #13 | Confirmation page served by the API, without login: GET only displays, POST confirms. The token is valid for 24 h and is single-use. Pending alerts of an incident that is already acknowledged or resolved are skipped with their reason | Óscar confirmed from the Mailpit email and the rate-of-change incident was acknowledged at level 1, without escalating |
| VIG-24 | #14 | `escalation` worker every 15 s: it moves up a level when `wait_s` expires, counted from when that level was notified (migration 0007); a level with no deliveries at all escalates immediately. Policies API for admin | The silence incident escalated to level 2 after 128 s ("nadie confirmó en 120 s", "nobody confirmed within 120 s"). In the story's test, level 1 escalated to 2 after 134 s, a confirmation at level 2 stopped the escalation, and the earlier incidents exhausted their last level after 300 s |
| VIG-21 | #15 | Single-use `t.me/<bot>?start=<token>` link valid for 7 days; the `telegram` worker stores the `chat_id` when it receives `/start` | Rosa Brigada was linked with a real bot; the previous link answered "no válido" ("not valid"), because a new one invalidates the previous one |
| VIG-22 | #16 | The dispatcher sends via Telegram with a button whose `callback_data` is the token; only the recipient can confirm; after the click the button is replaced by a note | Telegram went out 1 s after escalating and was confirmed with the button 7 s later. The button disappeared and the note "Confirmado por Rosa Brigada el 30/09/2026 18:57 (America/Lima)" ("Confirmed by Rosa Brigada on 30/09/2026 18:57") remained. The Telegram alert for Lucho, who has not linked it, was skipped and recorded |

## Sprint decisions

- **Confirmation:** confirming any alert acknowledges the incident. If someone else got there first, the alert is recorded as seen without changing who acknowledged; if the incident was already resolved, nothing changes.
- **Escalation:** `wait_s` counts from when the level was notified (`incidents.level_started_at`). The worker reads the current policy, so an admin's changes apply to incidents in progress.
- **Telegram:**
  - The admin generates the link and shares it with the contact.
  - Only the chat that received the alert can confirm it; anyone else gets a notice without incident data.
  - The bot token never reaches the logs: the httpx2 logger stays at WARNING and errors do not chain the original exception.
- **Independent channels:** if Telegram goes down, email keeps going out. A Telegram update that cannot be read is discarded and does not block the following ones.
- **Backlog review (PR #17):**
  - New stories VIG-33 to VIG-39: visual system, incident inbox, actions from the dashboard, contacts and groups, policies in the dashboard, audit and failed readings.
  - The `chat_id` never leaves the API.
  - A sprint 7 is added.

## Picking it up again

```bash
git switch main
make up && make seed
make lint test
make simulate ARGS="--scenario rimac --seed 42"
```

To receive alerts via Telegram:
1. Create a bot with @BotFather.
2. Put `WILLAY_TELEGRAM_BOT_TOKEN` and `WILLAY_TELEGRAM_BOT_USERNAME` (without `@`) in `.env`.
3. Generate a contact's link with `POST /v1/contacts/{id}/telegram-link` using an admin token (see README).

The emails can be seen in Mailpit: http://localhost:8025.

## Changes to the specification in this sprint

- `249eaa0` docs(spec): confirmation outcomes and no alerts after confirmation (PR #13)
- `035bc16` docs(spec): escalation timing and live policies (PR #14)
- `fa5f472` docs(spec): Telegram link lifetime and how it reaches the contact (PR #15)
- `caf4bdb` docs(spec): only the recipient confirms from the Telegram button (PR #16)
- `35d6223` docs(spec): a contact's chat_id never leaves the API (PR #17)
- `8e5847e` docs(spec): add panel and admin stories VIG-33 to VIG-39 with a sprint 7 (PR #17)

## To do

- [ ] **Validation interviews:** SPEC asked for at least 3 before Sprint 4 and for adjusting the backlog before Sprint 5; `docs/research/` is still empty. Sprint 5 builds the dashboard, precisely what they should shape the most.
- [ ] **WSL environment:** enable the Ubuntu WSL integration in Docker Desktop and install `make`. The live test was done from Windows because WSL had neither of the two.
- [ ] **Ports:** the other local project (`keycloak_custom` on 8080 and `pgsql_keycloak` on 5433) clashes with Vigía and leaves its containers in `Created`; it has to be stopped before `make up`. Decide whether to make the Keycloak ports configurable end to end, since its URL also lives in the realm, the dashboard and token validation.
- [ ] When confirming from Telegram, the message keeps the line "Si nadie lo confirma, Vigía avisará al siguiente nivel." ("If nobody confirms it, Vigía will notify the next level."), which no longer applies: remove it when editing.
- [ ] VIG-30 (`make demo`) needs to reset the demo data without losing the linked contacts: the 30 min cooldown prevents repeating the scenario right away.
- [ ] From previous sprints:
  - accept ADRs 0001–0006;
  - Node 24 in WSL and move the repo to the WSL file system;
  - decide whether to delete `refs/backup/*` and the local branches `feat/VIG-01` to `feat/VIG-11`.
  - The organization's name in the dashboard moved to VIG-33.

## Retro

- **Went well:** VIG-22 was delivered in two parts, each committed as soon as its tests passed, as the previous retro asked. The test with the real bot worked on the first try as far as the code was concerned: all the problems came from the environment.
- **To improve:** the live test guide assumed a WSL with Docker and `make`, and free ports, and did not warn that confirming the level 1 email stops the escalation before it reaches Telegram. Every test guide must start with an environment check.
- **To try:** in VIG-30, have `make demo` check the environment (Docker, ports) and reset the demo data before launching the scenario.
