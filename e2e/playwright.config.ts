import { defineConfig } from '@playwright/test';

/**
 * Against a stack that is already running (`make up` and `make seed`), never one it starts
 * itself: the point is the real dashboard, API and Keycloak together. WILLAY_E2E_CHANNEL picks
 * an installed browser instead of Playwright's Chromium (e.g. `msedge` on Windows).
 */
export default defineConfig({
  testDir: '.',
  timeout: 60_000,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.WILLAY_DASHBOARD_URL ?? 'http://localhost:4200',
    channel: process.env.WILLAY_E2E_CHANNEL || undefined,
    // The smallest screen SPEC promises (VIG-33): a common Android phone held upright.
    viewport: { width: 360, height: 780 },
  },
  // Some labels are longer in English, others in Spanish, so both are measured.
  projects: [
    { name: 'es', use: { locale: 'es-PE' } },
    { name: 'en', use: { locale: 'en-US' } },
  ],
});
