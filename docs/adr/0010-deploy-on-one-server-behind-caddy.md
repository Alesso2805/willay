# ADR-0010: Deploy on one server, behind Caddy, on one hostname

- **Status:** Proposed
- **Date:** 2026-10-04
- **Related:** SPEC.md › Backlog › VIG-42 and VIG-43; docs/runbooks/deploy.md; ADR-0001; ADR-0004

## Context

VIG-42 puts Willay on the internet so that anyone can try it from a link, at no cost. The stack is ten services: Postgres with TimescaleDB and PostGIS, Keycloak, Mailpit, the `migrate` container, the API, five workers and the dashboard. Together they need about 2 GB of memory and 10 GB of disk. Keycloak alone takes 0.8 GB.

Until now everything assumed `localhost`:
- the dashboard's build carried the API and Keycloak URLs;
- Keycloak ran in development mode;
- each service published its own port.

## Options

1. **A platform as a service** (Render, Railway, Fly.io). Ten services, a Postgres with two extensions those platforms rarely offer, and Keycloak's memory make it cost more than a server, with less control.
2. **Kubernetes** (managed or k3s). It is far more machinery than one demo needs, and one person would maintain it.
3. **One server with Docker Compose,** the same stack as on a laptop, with a proxy for HTTPS. The options for addressing the services:
   - **(a) a subdomain per service** (`app.`, `api.`, `auth.`, `mail.`): four names, four certificates, and CORS between them;
   - **(b) one hostname with a path per service:** one name, one certificate, and the browser sees a single origin.

## Decision

Option 3b: one server, Docker Compose, Caddy, one hostname.

- **`docker-compose.prod.yml` on top of `docker-compose.yml`.** The server's `.env` sets `COMPOSE_FILE` to both files, so `make up`, `make seed` and `make demo` work there unchanged. The overlay:
  - removes every published port with `!reset`, except Caddy's;
  - turns Keycloak to production mode.
- **Caddy** gets and renews the Let's Encrypt certificate on its own. It routes:
  - `/` to the dashboard;
  - `/api` to the API, with the prefix stripped (`--root-path` keeps the API's own links right);
  - `/auth` to Keycloak (`KC_HTTP_RELATIVE_PATH`);
  - `/correo` to Mailpit (`MP_WEBROOT`).

  Live events (SSE) are flushed as they come.
- **One dashboard image for any hostname.** The container writes `/config.json` from its environment when it starts. `main.ts` reads it before importing the app, whose modules read the URLs as they load.
- **Keycloak without a fixed hostname.** It takes its address from each request, so it answers as `https://<host>/auth` through Caddy and as `http://localhost:8081/auth` through an SSH tunnel. That is safe here:
  - Caddy serves only the configured hostname and sets the `X-Forwarded-*` headers;
  - Keycloak publishes nothing but `127.0.0.1:8081`;
  - Caddy answers 404 for the admin console and the `master` realm, which live behind the tunnel.
- **Credentials:** `make secrets HOST=…` writes the server's `.env` from `.env.example`, with fresh 48-character hex values (hex, because they go inside database URLs). It never overwrites an existing `.env`.
- **Target:** an Oracle Cloud Always Free ARM server (up to 4 OCPUs and 24 GB, for free) and a free DuckDNS hostname. Every image the stack uses is published for arm64 and amd64.

## Consequences

- The demo costs nothing. The trade-offs:
  - Oracle's ARM capacity is not always available when creating the server;
  - a free-tier account's idle server can be reclaimed, which upgrading to Pay As You Go avoids at no cost within the limits;
  - DuckDNS is a third party the hostname depends on.
- Moving to another server or provider is the same runbook: Docker, a hostname pointing to it, and `make secrets`, `make up` and `make seed`.
- A single server is a single point of failure, which is acceptable for a demo. A real deployment would add backups of the Postgres volume and monitoring, and would likely move to a managed Postgres with TimescaleDB.
- The first start builds the images on the server (about 10 minutes on ARM). Prebuilt images in a registry would shorten it if updates become frequent.
- Integration tests and CI do not deploy. CI only checks that the overlay stays valid (`docker compose config`). The overlay itself was checked end to end on `https://localhost`:
  - sign-in through `/auth`;
  - data and live events through `/api`;
  - an incident's email in `/correo`;
  - its confirmation link through `/api/confirmar`;
  - Keycloak's admin console blocked publicly and reachable through the loopback port.
