# Sprint 7: latency, load test, guided demo, bilingual product and dark mode (VIG-28, 29, 30, 40, 41)

**Status as of 2026-10-05:** all five stories (25 points, counting VIG-41 added mid-sprint) are merged into `main` with green CI and were checked on the real stack. One item is open: VIG-30's recorded video.

The plan placed this sprint between January 4 and 17. Order: VIG-28, 29, 30, 40, then 41. The suites ended at 914 backend tests and 298 dashboard tests. Neither optional story (VIG-31, VIG-37) was started.

## What was delivered

| Story | PRs | Result | Verification on the real stack |
| --- | --- | --- | --- |
| VIG-28 | #54, #55 | One `correlation_id` per batch, carried by JSON logs from the reading to the incident and its alerts. Each incident's first alert logs `received_to_alert_seconds`. `make latency` reports p50 and p95 from the database | A RIM-CHA-01 drop was followed through the logs by its id alone: from the API to the evaluator to the dispatcher, reading to email in 54 ms. `make latency` reported p95 0.05 s on a threshold incident in the isolation organization |
| VIG-29 | #57 | `make loadtest`: its own "Carga" organization with 50 stations and a rule each, 30 minutes at one reading per station every 10 s, then a verdict against SPEC | The full 30-minute run passed: 9,000 batches, none rejected, no reading unevaluated after 120 s, 50 incidents; p50 0.13 s, p95 0.50 s, max 0.84 s against a 30 s target |
| VIG-30 | #58, #59 | `make demo` plays SPEC's Rímac scenario, narrates it and judges it. Level 2 acknowledges by Telegram, or from the email when no one has Telegram. Each run starts from a clean demo organization. The README covers it, with screenshots | Passed three times: twice with the product owner pressing the Telegram buttons on their phone, once from the email. A first run failed for the right reason: someone acknowledged at level 1 from the dashboard |
| VIG-40 | #60–#70 | Spanish and English:<br>• the dashboard speaks each user's language, saved for them, and Keycloak's login follows it;<br>• API errors carry a stable `code` and a message in the request's language;<br>• timeline reasons are codes, translated for each reader;<br>• each contact has a language (or follows the organization's) for emails, Telegram and the confirmation page | Every page checked in English in Edge. API errors checked with `curl` in both languages. An English contact got the email through Mailpit and the Telegram alert, button and replies in English (integration tests). The confirmation page follows the contact, or the browser for an unknown link |
| VIG-41 | #71, #72, #73 | Light and dark mode. The dashboard follows the system unless the user picks a theme in that browser. Colors are semantic CSS variables, so switching repaints without redrawing. The visual catalog has a dark shade for each state, and the base map darkens with a filter. The confirmation page follows the device | Checked in Edge at 1280 and 360 px in both themes:<br>• dark is applied before the app loads;<br>• a choice survives a reload;<br>• the page is not redrawn.<br>Keycloak's login already followed the system's dark mode |

Also merged during the sprint:
- **#56:** CI pulls its base images from ghcr.io authenticated, since anonymous pulls had started to answer 429.
- **A security fix inside #62:** Leaflet inserted tooltip strings as HTML. A zone or station named with markup would have run in the browser of whoever hovered over it. Tooltips now carry plain text.

## Sprint decisions

- **Latency:** measured from logs and a database report rather than a metrics server, because the MVP has no Prometheus. The `correlation_id` belongs to the batch, so every reading in it shares one trace.
- **Load test:** runs in its own organization, so it never touches the demo data. It checks SPEC's two numbers: zero unevaluated readings and p95 < 30 s.
- **Demo:** clearing the demo organization needs `willay_owner`, because incident events are append-only for the app role. The intro recommends watching as `rimac-viewer`, so a click in the dashboard cannot end the story at level 1.
- **i18n with i18next** (ADR-0008):
  - plain `t()` functions, so pure presentation code and its specs stay framework-free;
  - JSON catalogs typed from Spanish, and a test that fails on a missing key or placeholder.

  The user's language lives in the database. The backend uses the same `{{x}}` catalog format.
- **Who gets which language:**
  - a contact without a language follows their organization's, which is not copied;
  - anyone the system cannot tie to a contact gets their Telegram app's or browser's language: a stranger writing to the bot or pressing someone else's button, or an unknown confirmation link.
- **Dark mode with CSS variables** (ADR-0009):
  - pages use colors by role, never a fixed gray;
  - the contrast tests read `styles.css` and measure both themes;
  - the choice is kept in the browser, not the database, because it must apply before the app loads and often depends on the device.

## Changes to the specification in this sprint

- `23cd950` docs(spec): users keep their dashboard language (VIG-40)
- `0accc24` docs(spec): API errors answer with a code and a localized message (VIG-40)
- `7155b08` docs(spec): contacts and organizations have a language for their alerts (VIG-40)
- `b9f0001` docs(spec): who gets which language when no contact is known (VIG-40)
- `ad07bb7` docs(spec): light and dark mode as VIG-41 (Sprint 7)

## Retro

- **Went well:** the tests and the live checks found what review would have missed:
  - the XSS in map tooltips;
  - an existing gray below AA on the page background;
  - a click on the already active language not counting as a choice.

  Rebasing stacked PRs became routine with a script that checks the tree is unchanged before pushing.
- **To improve:** VIG-40 was a stack of 11 PRs. Small PRs kept each review readable, but they took most of the merge time, and the sprint retro had already asked for shallower stacks.
- **To try:** for the public release, record the video and the screenshots from a deployed instance, so what a visitor sees is what the README shows.
