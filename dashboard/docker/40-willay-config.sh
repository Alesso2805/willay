#!/bin/sh
# VIG-42: the dashboard's URLs for this deployment, written from the environment when the
# container starts (nginx runs every script in /docker-entrypoint.d/). src/app/settings.ts reads
# them; without these variables they are the local ones.
set -eu
cat > /usr/share/nginx/html/config.json <<JSON
{
  "apiUrl": "${WILLAY_API_URL:-http://localhost:8000}",
  "oidc": {
    "authority": "${WILLAY_OIDC_AUTHORITY:-http://localhost:8080/realms/willay}",
    "clientId": "${WILLAY_OIDC_CLIENT_ID:-willay-dashboard}"
  }
}
JSON
