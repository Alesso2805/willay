import { expect, test } from '@playwright/test';

/**
 * VIG-42 and VIG-43 on a server: the production overlay behind Caddy, on one hostname. Only
 * when asked, because it needs a deployed server rather than the local stack:
 *   WILLAY_E2E_DEPLOYED=1 WILLAY_DASHBOARD_URL=https://<host> npx playwright test deployed.spec.ts
 */

test.skip(!process.env.WILLAY_E2E_DEPLOYED, 'only against a deployed server (WILLAY_E2E_DEPLOYED=1)');
// A rehearsal on https://localhost has Caddy's local certificate, which no browser trusts.
test.use({ ignoreHTTPSErrors: true });

/** Never reachable from the internet (ADR-0010). The admin console is reached through SSH. */
const CLOSED = [
  '/auth/admin/',
  '/auth/admin/master/console/',
  '/auth/realms/master/.well-known/openid-configuration',
  // The account console and its API: where a demo account could change the shared password.
  '/auth/realms/willay/account',
  '/auth/realms/willay/account/credentials/password',
];

for (const path of CLOSED) {
  test(`${path} is closed`, async ({ request }) => {
    expect((await request.get(path, { maxRedirects: 0 })).status()).toBe(404);
  });
}

test('the dashboard, the API, the sign-in and the mailbox answer on one hostname', async ({
  request,
  baseURL,
}) => {
  const config = await (await request.get('/config.json')).json();
  expect(config.apiUrl).toBe(`${baseURL}/api`);
  expect(config.oidc.authority).toBe(`${baseURL}/auth/realms/willay`);
  expect(config.mailUrl).toBe(`${baseURL}/correo/`);
  expect((await request.get('/api/health')).status()).toBe(200);
  const signIn = await request.get('/auth/realms/willay/.well-known/openid-configuration');
  expect(signIn.status()).toBe(200);
  expect((await signIn.json()).issuer).toBe(`${baseURL}/auth/realms/willay`);
  expect((await request.get('/correo/')).status()).toBe(200);
});

test('the dashboard and the sign-in page show the Willay icon', async ({ request, baseURL }) => {
  const icon = await request.get('/icon.svg');
  expect(icon.status()).toBe(200);
  expect(icon.headers()['content-type']).toContain('image/svg+xml');
  // The sign-in page itself, as the dashboard opens it: the realm's login theme sets the icon.
  const { oidc } = await (await request.get('/config.json')).json();
  const query = new URLSearchParams({
    client_id: oidc.clientId,
    redirect_uri: `${baseURL}/`,
    response_type: 'code',
    scope: 'openid',
    code_challenge: 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
    code_challenge_method: 'S256',
  });
  const signIn = await request.get(`/auth/realms/willay/protocol/openid-connect/auth?${query}`);
  expect(signIn.status()).toBe(200);
  expect(await signIn.text()).toMatch(/href="[^"]*\/login\/willay\/img\/favicon\.ico"/);
});

test('the public demo shows its shared password, and nothing else of the server', async ({
  request,
}) => {
  const config = await (await request.get('/config.json')).json();
  test.skip(config.demo === null, 'the public demo is off on this server');
  expect(Object.keys(config).sort()).toEqual(['apiUrl', 'demo', 'mailUrl', 'oidc']);
  expect(config.demo).toEqual({ password: 'willay-demo' });
});
