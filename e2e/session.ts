import { readFileSync } from 'node:fs';
import type { Page } from '@playwright/test';

/** The seed users' password: from the environment, or else from the stack's `.env`. */
export function devPassword(): string {
  if (process.env.WILLAY_DEV_USER_PASSWORD) return process.env.WILLAY_DEV_USER_PASSWORD;
  const line = readFileSync(new URL('../.env', import.meta.url), 'utf8')
    .split(/\r?\n/)
    .find((l) => l.startsWith('WILLAY_DEV_USER_PASSWORD='));
  if (!line) throw new Error('WILLAY_DEV_USER_PASSWORD is neither set nor in .env');
  return line.slice(line.indexOf('=') + 1).trim();
}

/**
 * Signs in through Keycloak, which asks for the username first and the password next. The
 * session lives in the tab's sessionStorage, so the same page must be used afterwards.
 */
export async function signIn(page: Page, user: string, password = devPassword()): Promise<void> {
  await page.goto('/');
  await page.getByRole('button', { name: /^(Iniciar sesión|Sign in)$/ }).click();
  await page.locator('#username').fill(user);
  await page.locator('#username').press('Enter');
  await page.locator('#password').fill(password);
  await page.locator('#password').press('Enter');
}
