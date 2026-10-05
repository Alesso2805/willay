#!/bin/sh
# VIG-42: the dashboard's URLs for this deployment, written from the environment when the
# container starts (nginx runs every script in /docker-entrypoint.d/). src/app/settings.ts reads
# them; without these variables they are the local ones.
set -eu
# The public demo (VIG-43): its accounts' shared password is meant to be seen.
demo=null
if [ "${WILLAY_DEMO_MODE:-false}" = "true" ]; then
  demo="{ \"password\": \"${WILLAY_DEMO_PASSWORD:-}\" }"
fi
cat > /usr/share/nginx/html/config.json <<JSON
{
  "apiUrl": "${WILLAY_API_URL:-http://localhost:8000}",
  "oidc": {
    "authority": "${WILLAY_OIDC_AUTHORITY:-http://localhost:8080/realms/willay}",
    "clientId": "${WILLAY_OIDC_CLIENT_ID:-willay-dashboard}"
  },
  "mailUrl": "${WILLAY_MAIL_URL:-http://localhost:8025}",
  "demo": $demo
}
JSON
