# ADR-0009: Light and dark mode with CSS variables

- **Status:** Proposed
- **Date:** 2026-10-04
- **Related:** SPEC.md › Backlog › VIG-41; SPEC.md › Non-functional requirements › Accessibility; ADR-0008

## Context

VIG-41 adds a dark mode. The dashboard follows the system's mode unless the user picks Light or Dark. Two constraints shape the design:

- **Accessibility.** SPEC requires WCAG 2.1 AA, and the visual catalog (VIG-33) measures each state's contrast in a test. A dark mode doubles that work: every state needs a dark shade that passes the same thresholds.
- **Operations.** The system can switch at sunset while an operator is writing a comment. The theme must not redraw the page and lose what they typed. The i18n switch (ADR-0008) does redraw the shell, but language never changes on its own.

Before this story, pages used about 330 fixed Tailwind colors (`text-slate-700`, `bg-white`…). The catalog held hex values in TypeScript that components put in inline styles.

## Options

1. **`dark:` variants on every class.** This is Tailwind's default, but it doubles every color class (`bg-white dark:bg-slate-900`) across 21 files. Each new screen must remember to add them, and nothing tests that it did.
2. **Theme in a signal, colors picked in TypeScript.** Components read the theme and choose a palette. Every badge, notice and marker has to react to it, and Leaflet layers need redrawing.
3. **Semantic CSS variables switched by a class.** Pages use colors by role (`bg-surface`, `text-ink-muted`) and the catalog names a tone (`var(--tone-red-fg)`). A `dark` class on `<html>` redefines the variables, and the browser repaints without touching the DOM.
4. **Invert Tailwind's gray scale in dark mode.** Redefining `--color-slate-900` as a light value restyles everything without editing pages. But a class would no longer mean what it says (`bg-white` would be dark), and accent colors do not invert cleanly.

## Decision

Option 3:

- **Semantic colors.** These are defined in `@theme` in `styles.css`:
  - backgrounds: `canvas`, `surface`, `surface-muted`;
  - borders: `line-soft`, `line`, `line-strong`;
  - text: `ink`, `ink-soft`, `ink-muted`, `ink-subtle`;
  - accent: `accent`, `accent-strong`, `accent-soft`;
  - destructive actions: `danger`, `danger-strong`.

  Pages use these, never a fixed gray. Brand and navigation colors (`brand-*`, `night-*`) are the same in both themes.
- **Dark values.** `:root.dark` redefines every semantic color and tone. A test fails if one is left to inherit its light value.
- **Catalog.** A state names a tone (`red`, `orange`, `amber`, `green`, `blue`, `slate`, `alarm`). Its `foreground`, `background` and `map` are `var(--tone-…)` strings, which badges, notices and markers already use in inline styles.
- **Leaflet zones.** These are SVG paths with `stroke` and `fill` attributes, and an attribute cannot hold a CSS variable. They get a `tone-…` class that `styles.css` colors instead, since CSS overrides presentation attributes.
- **Contrast tests read `styles.css`.** The catalog spec parses the light and dark blocks and measures, in both themes:
  - each text level on each background (≥ 4.5:1);
  - each badge label on its color (≥ 4.5:1);
  - each map color against the base map and under a white marker icon (≥ 3:1);
  - each notice (≥ 4.5:1).

  The colors live once, in the CSS the browser paints, and the test measures exactly that.
- **Choice and storage.** `ThemeService` keeps System, Light or Dark in this browser's `localStorage`, not in the database:
  - the theme must apply before the app loads and before the API says who the user is;
  - the right theme often depends on the device (a phone at night, a monitor in an office).

  This differs on purpose from the language, which follows the user everywhere.
- **No white flash.** An inline script in `index.html` applies the same rule before Angular boots. A test runs that script and checks it against the service's rule and storage key.
- **Native controls.** `color-scheme` is set per theme, so scrollbars, selects and date pickers match.

## Consequences

- A theme switch repaints and never redraws, so forms, scroll position and map state survive it.
- New screens get dark mode for free as long as they use semantic colors. A fixed gray shows up in review as a class that does not follow the theme.
- The palettes cannot be measured without reading CSS, so the catalog spec reads `styles.css` from disk. The dashboard has no Node types, which costs one `@ts-expect-error`.
- Keycloak's login (`keycloak.v2` theme) already follows the system's mode. It cannot follow a choice made inside the dashboard, which lives on another origin.
- The confirmation page served by the API has no login, so it follows the system's mode through `prefers-color-scheme`.
