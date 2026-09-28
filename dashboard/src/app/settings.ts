/**
 * URLs del entorno local (docker compose). Para otros entornos se sustituirá por
 * configuración en tiempo de ejecución; no contiene secretos: el cliente OIDC es público.
 */
export const settings = {
  apiUrl: 'http://localhost:8000',
  oidc: {
    authority: 'http://localhost:8080/realms/vigia',
    clientId: 'vigia-dashboard',
  },
} as const;
