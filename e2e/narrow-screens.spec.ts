import { type Page, expect, test } from '@playwright/test';
import { signIn } from './session';

/**
 * VIG-33: the main views are usable at 360 px without horizontal scrolling. jsdom has no layout,
 * so this needs a real browser and real data: an admin of the seed's Rímac organization sees
 * every page. A table or a map may scroll inside its own box; the page itself may not.
 */

const PAGES = [
  '/',
  '/mapa',
  '/incidentes',
  '/zonas',
  '/estaciones',
  '/reglas',
  '/contactos',
  '/contactos/grupos',
  '/contactos/politicas',
  '/lecturas-fallidas',
  '/auditoria',
  '/organizacion',
];

/** How much wider than the screen the page is, and the first elements that stick out. */
async function overflow(page: Page): Promise<{ excess: number; culprits: string[] }> {
  return page.evaluate(() => {
    const root = document.documentElement;
    const width = root.clientWidth;
    const scrollsOnItsOwn = (element: Element) => {
      for (let p = element.parentElement; p && p !== document.body; p = p.parentElement) {
        if (/(auto|scroll|hidden|clip)/.test(getComputedStyle(p).overflowX)) return true;
      }
      return false;
    };
    const culprits = [...document.querySelectorAll('body *')]
      .filter((element) => {
        const box = element.getBoundingClientRect();
        return box.width > 0 && box.right > width + 1 && !scrollsOnItsOwn(element);
      })
      .slice(0, 5)
      .map((element) => {
        const name = element.tagName.toLowerCase();
        const text = (element.textContent ?? '').trim().slice(0, 40);
        return text ? `${name} "${text}"` : name;
      });
    return { excess: root.scrollWidth - width, culprits };
  });
}

async function expectNoHorizontalScroll(page: Page, where: string): Promise<void> {
  const { excess, culprits } = await overflow(page);
  expect(excess, `${where} is ${excess} px wider than the screen: ${culprits.join('; ')}`).toBeLessThanOrEqual(0);
}

test.describe.configure({ mode: 'serial' });

let page: Page;

// One page for the whole run: the session lives in the tab's sessionStorage, so a new page
// per test would mean signing in again every time.
test.beforeAll(async ({ browser }, testInfo) => {
  const { viewport, locale, baseURL } = testInfo.project.use;
  page = await browser.newPage({ viewport, locale, baseURL });
});

test.afterAll(async () => {
  await page.close();
});

test('the sign-in screen, then signing in', async ({}, testInfo) => {
  const language = testInfo.project.use.locale?.slice(0, 2);
  await page.goto('/');
  await page.getByRole('button', { name: /^(Iniciar sesión|Sign in)$/ }).waitFor();
  await expectNoHorizontalScroll(page, 'the sign-in screen');

  await signIn(page, 'rimac-admin');
  // Below 1024 px the navigation folds into a menu button.
  await page.getByRole('button', { name: /^(Menú|Menu)$/ }).waitFor({ timeout: 30_000 });

  // A language saved for the user wins over the browser's (VIG-40): then this run would not be
  // measuring the language it says it is.
  const shown = await page.evaluate(() => document.documentElement.lang.slice(0, 2));
  expect(
    shown,
    `rimac-admin has a saved language; to measure both, clear it: UPDATE core.users SET language = NULL WHERE email = 'admin@rimac.willay.test'`,
  ).toBe(language);
});

for (const path of PAGES) {
  test(`${path} at 360 px`, async () => {
    await page.goto(path);
    await page.locator('h1').first().waitFor();
    // The page's data comes over REST right after; give it a moment to lay out.
    await page.waitForTimeout(1_000);
    await expectNoHorizontalScroll(page, path);
  });
}

test('an incident at 360 px', async () => {
  await page.goto('/incidentes?estado=open&estado=acknowledged&estado=resolved');
  await page.locator('h1').first().waitFor();
  await page.waitForTimeout(1_000);
  const links = page.locator('a[href^="/incidentes/"]');
  test.skip((await links.count()) === 0, 'no incident in this organization yet');
  await links.first().click();
  await page.locator('h1').first().waitFor();
  await page.waitForTimeout(1_000);
  await expectNoHorizontalScroll(page, 'the incident detail');
});
