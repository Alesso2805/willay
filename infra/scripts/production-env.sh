#!/bin/sh
# Writes the .env of a server (VIG-42): .env.example with a fresh random value for every
# credential, plus the hostname and the production compose overlay. With DEMO=1, the public
# demo too (VIG-43). Run from the repository root through
# `make secrets HOST=willay.example.org [DEMO=1]`. It never overwrites an existing .env.
set -eu

host="${1:-}"
demo="${2:-}"
if [ -z "$host" ]; then
  echo "Usage: make secrets HOST=<the server's hostname, e.g. willay.duckdns.org>" >&2
  exit 2
fi
if [ -e .env ]; then
  echo ".env already exists: remove it first if you really mean to replace its credentials." >&2
  exit 1
fi

# Hex only: these values end up inside database URLs, where /, + or = would break them.
random() {
  od -An -N24 -tx1 /dev/urandom | tr -d ' \n'
}

umask 077
while IFS= read -r line; do
  case "$line" in
    POSTGRES_PASSWORD=* | WILLAY_OWNER_PASSWORD=* | WILLAY_APP_PASSWORD=* | KEYCLOAK_DB_PASSWORD=* | \
      KEYCLOAK_ADMIN_PASSWORD=* | WILLAY_DEV_USER_PASSWORD=*)
      echo "${line%%=*}=$(random)"
      ;;
    *) echo "$line" ;;
  esac
done < .env.example > .env

cat >> .env <<EOF

# --- Server (written by make secrets) ---
COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml
WILLAY_HOSTNAME=$host
EOF

if [ -n "$demo" ] && [ "$demo" != "0" ]; then
  cat >> .env <<EOF

# --- Public demo (VIG-43): demo accounts, the scenario button and the demo worker ---
COMPOSE_PROFILES=demo
WILLAY_DEMO_MODE=true
# Shown on the sign-in screen on purpose: anyone may try the demo.
WILLAY_DEMO_PASSWORD=willay-demo
EOF
fi

echo "Wrote .env for https://$host with new credentials (readable only by you)."
if [ -n "$demo" ] && [ "$demo" != "0" ]; then
  echo "Public demo on: demo-admin, demo-operator and demo-viewer, password willay-demo."
fi
echo "Next: make up, then make seed."
