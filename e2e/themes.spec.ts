import { type Page, expect, test } from '@playwright/test';
import { signIn } from './session';

/**
 * VIG-41 in a real browser, where jsdom cannot look: the base map darkens with the theme, and
 * switching themes redraws nothing, so a half-written form survives it.
 */

test.describe.configure({ mode: 'serial' });

let page: Page;

test.beforeAll(async ({ browser }, testInfo) => {
  const { locale, baseURL } = testInfo.project.use;
  page = await browser.newPage({ locale, baseURL, viewport: { width: 1280, height: 800 } });
  await signIn(page, 'rimac-admin');
  await page.getByRole('navigation', { name: /^(Principal|Main)$/ }).waitFor({ timeout: 30_000 });
});

test.afterAll(async () => {
  await page.close();
});

/** The CSS filter on the map's tiles, once the live map has drawn them. */
async function tileFilter(): Promise<string> {
  await page.goto('/mapa');
  const pane = page.locator('.leaflet-tile-pane');
  await pane.waitFor({ state: 'attached' });
  return pane.evaluate((element) => getComputedStyle(element).filter);
}

test('the base map darkens with the theme, on the same tiles', async () => {
  // With the System choice the dashboard follows the device, as SPEC asks.
  await page.emulateMedia({ colorScheme: 'light' });
  expect(await tileFilter()).not.toContain('invert');
  await page.emulateMedia({ colorScheme: 'dark' });
  expect(await tileFilter()).toContain('invert');
  await page.emulateMedia({ colorScheme: 'light' });
});

test('switching themes redraws nothing: a half-written form survives it', async () => {
  await page.goto('/contactos');
  await page.getByRole('button', { name: /^(Nuevo contacto|New contact)$/ }).click();
  const name = page.locator('input[formcontrolname="full_name"]');
  await name.fill('A name half written');
  // A mark on the page: if switching themes redrew it, the mark would be gone.
  await page.evaluate(() => document.querySelector('main')?.setAttribute('data-probe', 'kept'));

  await page.getByRole('button', { name: /^(Oscuro|Dark)$/ }).first().click();
  await expect(page.locator('html')).toHaveClass(/\bdark\b/);
  await expect(name).toHaveValue('A name half written');
  expect(await page.evaluate(() => document.querySelector('main')?.dataset['probe'])).toBe('kept');

  // Back to following the device, so the choice does not outlive the test in this browser.
  await page.getByRole('button', { name: /^(Sistema|System)$/ }).first().click();
});
