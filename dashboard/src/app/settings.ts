/**
 * Local environment URLs (docker compose). Other environments will replace this with runtime
 * configuration. It holds no secrets: the OIDC client is public.
 */
export const settings = {
  apiUrl: 'http://localhost:8000',
  oidc: {
    authority: 'http://localhost:8080/realms/willay',
    clientId: 'willay-dashboard',
  },
} as const;
