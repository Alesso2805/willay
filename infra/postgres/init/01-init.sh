#!/usr/bin/env bash
# Runs as superuser only once, when the data volume is empty.
# Creates what a migration run as willay_owner cannot create (ADR-0005):
#   - roles willay_owner, willay_app and keycloak (a role cannot create itself)
#   - databases willay and keycloak
#   - extensions timescaledb and postgis (they are not "trusted": they require a superuser)
set -euo pipefail

: "${WILLAY_OWNER_PASSWORD:?missing WILLAY_OWNER_PASSWORD}"
: "${WILLAY_APP_PASSWORD:?missing WILLAY_APP_PASSWORD}"
: "${KEYCLOAK_DB_PASSWORD:?missing KEYCLOAK_DB_PASSWORD}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v owner_pw="$WILLAY_OWNER_PASSWORD" \
  -v app_pw="$WILLAY_APP_PASSWORD" \
  -v kc_pw="$KEYCLOAK_DB_PASSWORD" <<'SQL'
CREATE ROLE willay_owner LOGIN PASSWORD :'owner_pw';
CREATE ROLE willay_app LOGIN PASSWORD :'app_pw';
CREATE ROLE keycloak LOGIN PASSWORD :'kc_pw';

CREATE DATABASE willay OWNER willay_owner;
CREATE DATABASE keycloak OWNER keycloak;

-- Nobody but Willay's roles connects to its database.
REVOKE ALL ON DATABASE willay FROM PUBLIC;
GRANT CONNECT ON DATABASE willay TO willay_app;
REVOKE ALL ON DATABASE keycloak FROM PUBLIC;

\connect willay
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS postgis;
-- In PG15+ public is no longer writable by PUBLIC; we make it explicit.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
