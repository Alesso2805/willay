import { applySettings, loadSettings, settings } from './settings';

const LOCAL = structuredClone(settings);
const DEPLOYED = {
  apiUrl: 'https://willay.example.org/api',
  oidc: {
    authority: 'https://willay.example.org/auth/realms/willay',
    clientId: 'willay-dashboard',
  },
};

function respond(body: unknown, status = 200): typeof fetch {
  return () => Promise.resolve(new Response(JSON.stringify(body), { status }));
}

afterEach(() => {
  settings.apiUrl = LOCAL.apiUrl;
  settings.oidc = { ...LOCAL.oidc };
});

describe('settings', () => {
  it('takes the URLs of the deployment from its config.json', async () => {
    await loadSettings(respond(DEPLOYED));
    expect(settings).toEqual(DEPLOYED);
  });

  it('keeps the local URLs without a config.json, or with one it cannot read', async () => {
    await loadSettings(respond({}, 404));
    await loadSettings(() => Promise.reject(new TypeError('offline')));
    await loadSettings(() => Promise.resolve(new Response('<html>', { status: 200 })));
    expect(settings).toEqual(LOCAL);
  });

  it('ignores what is missing or not text, and the trailing slash of the API', () => {
    applySettings({ apiUrl: 'https://willay.example.org/api/', oidc: { clientId: 7 } });
    expect(settings.apiUrl).toBe('https://willay.example.org/api');
    expect(settings.oidc).toEqual(LOCAL.oidc);
    applySettings(null);
    applySettings('nonsense');
    expect(settings.apiUrl).toBe('https://willay.example.org/api');
  });
});
