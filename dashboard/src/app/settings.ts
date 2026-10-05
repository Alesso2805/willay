/**
 * Where the API and Keycloak are. Locally, the ports docker compose publishes on localhost. A
 * deployed dashboard reads them from /config.json, which its container writes from the
 * environment when it starts (VIG-42), so one image serves any hostname. It holds no secrets:
 * the OIDC client is public.
 */
export interface Settings {
  apiUrl: string;
  oidc: { authority: string; clientId: string };
}

export const settings: Settings = {
  apiUrl: 'http://localhost:8000',
  oidc: {
    authority: 'http://localhost:8080/realms/willay',
    clientId: 'willay-dashboard',
  },
};

/**
 * Before the app loads: the deployment's /config.json over the local values. Without one (the
 * development server, a test), or with one that is not readable, the local values stay.
 */
export async function loadSettings(fetchConfig: typeof fetch = fetch): Promise<void> {
  try {
    const response = await fetchConfig('config.json', { cache: 'no-store' });
    if (!response.ok) return;
    applySettings(await response.json());
  } catch {
    // No config.json, or not JSON: the local values stay.
  }
}

export function applySettings(config: unknown): void {
  if (typeof config !== 'object' || config === null) return;
  const { apiUrl, oidc } = config as {
    apiUrl?: unknown;
    oidc?: { authority?: unknown; clientId?: unknown };
  };
  if (typeof apiUrl === 'string' && apiUrl) settings.apiUrl = apiUrl.replace(/\/+$/, '');
  if (typeof oidc?.authority === 'string' && oidc.authority)
    settings.oidc.authority = oidc.authority;
  if (typeof oidc?.clientId === 'string' && oidc.clientId) settings.oidc.clientId = oidc.clientId;
}
