# ADR-0008: The dashboard in several languages with i18next

- **Status:** Accepted on 2026-10-13
- **Date:** 2026-10-04
- **Related:** SPEC.md › Backlog › VIG-40; SPEC.md › Database schema (`users.language`)

## Context

VIG-40 makes Willay bilingual. Every visible text lives in translation files for `es` and `en`, and none is hard-coded. Each user picks their language, and a test fails if a key is missing in either language. Spanish stays the default.

The dashboard has about 700 texts in 60 files. Many are built in pure presentation functions (`*-presentation.ts`): the timeline in words, map tooltips, audit changes. Their specs run without Angular's TestBed. The product may later speak more languages and work with translators, so adding a language or a text should mean editing a file, not code.

## Options

1. **Angular's built-in i18n (`@angular/localize`).** It is official and uses XLIFF for translators. But it compiles one build per language, so switching means reloading another build, and the Docker image serves several copies. Texts built in TypeScript need `$localize`, resolved at build time.
2. **Transloco.** Its JSON files load at runtime and it has key-extraction tools. It translates through Angular's dependency injection, so pure functions and their specs would depend on the framework. It also has to keep up with every Angular major version.
3. **ngx-translate.** It has the same coupling to Angular, with fewer guarantees.
4. **i18next.** It does not depend on any framework and has typed keys, plural rules from `Intl.PluralRules` and a JSON format that translation platforms (Crowdin, Lokalise, Weblate, Locize) import directly. It has been actively maintained since 2011.
5. **An in-house translator.** It has no dependencies, but plurals, interpolation and the format for translators would all be ours to maintain.

## Decision

Option 4, i18next, in `dashboard/src/app/i18n/`:

- **Files.** One JSON file per language in `src/i18n/`, in i18next's JSON v4 format: nested keys by area (`nav.home`, `states.incident.open`), `{{name}}` placeholders and `_one`/`_many`/`_other` plural suffixes.
- **Typed keys.** `i18next.d.ts` types every key from `es.json`. A key that does not exist is a compile error, also in templates.
- **Completeness.** `translations.spec.ts` holds every language to Spanish: the same keys, the same placeholders, no empty text, and every plural form the language's grammar needs. Spanish needs `many` (1,000,000), or i18next shows the key.
- **Lazy loading.** Every language is its own chunk, Spanish included, downloaded before the first render only by whoever uses it. Texts and languages do not grow the bundle everyone downloads. There is no fallback language: the spec above makes it unnecessary.
- **One translator.** `t(key, options)` is a plain function. Pure functions use it as they are, and specs start in Spanish from `src/test-setup.ts`, which also fails a test on any key that has no text.
- **Language changes.** The app shell is drawn again from scratch (`*appRedrawOn`), so every text, including those computed in TypeScript, is translated anew. Services such as the session and the live channel carry on.
- **Which language.**
  1. The one saved for the user in `core.users.language`, which follows them to any device.
  2. Otherwise, the one this browser used last.
  3. Otherwise, the browser's own.
  4. Otherwise, Spanish.

  A language picked on the sign-in screen is saved once the user signs in.
- **Dates and numbers.** `Intl` formats them per language: `es-PE` and `en-US`, always with a 24-hour clock, and with the month by name in English. Ages ("hace 3 min", "3m ago") come from `Intl.RelativeTimeFormat`, so they need no keys.
- **Around the dashboard.** API requests carry `Accept-Language` for the localized errors of VIG-40d. Keycloak's sign-in page opens in the same language (OIDC `ui_locales`; the realm already offers `es` and `en`).

User-entered data (zone, station and contact names) is shown as entered and never translated.

## Consequences

- Adding a language takes four steps: add its JSON, add it to `LANGUAGES` and `LOCALES`, and add it to the database CHECK constraints. No page changes.
- A missing key fails the build or a test. It never reaches the screen as a raw key.
- i18next adds about 40 kB to the initial bundle (13 kB compressed). The warning budget goes from 550 to 600 kB, while the translations themselves stay out of it.
- Changing the language resets what is on screen, including a half-filled form. Users rarely change language, and the redraw keeps the code simple everywhere else.
- The backend messages (emails, Telegram, the confirmation page and API errors, VIG-40d and 40e) follow their own ADR or an amendment. The direction is gettext/Babel `.po` files, Python's standard, which the same translation platforms read.
