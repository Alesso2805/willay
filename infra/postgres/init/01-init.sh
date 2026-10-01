#!/usr/bin/env bash
# Runs as superuser only once, when the data volume is empty.
# Creates what a migration run as vigia_owner cannot create (ADR-0005):
#   - roles vigia_owner, vigia_app and keycloak (a role cannot create itself)
#   - databases vigia and keycloak
#   - extensions timescaledb and postgis (they are not "trusted": they require a superuser)
set -euo pipefail

: "${VIGIA_OWNER_PASSWORD:?missing VIGIA_OWNER_PASSWORD}"
: "${VIGIA_APP_PASSWORD:?missing VIGIA_APP_PASSWORD}"
: "${KEYCLOAK_DB_PASSWORD:?missing KEYCLOAK_DB_PASSWORD}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v owner_pw="$VIGIA_OWNER_PASSWORD" \
  -v app_pw="$VIGIA_APP_PASSWORD" \
  -v kc_pw="$KEYCLOAK_DB_PASSWORD" <<'SQL'
CREATE ROLE vigia_owner LOGIN PASSWORD :'owner_pw';
CREATE ROLE vigia_app LOGIN PASSWORD :'app_pw';
CREATE ROLE keycloak LOGIN PASSWORD :'kc_pw';

CREATE DATABASE vigia OWNER vigia_owner;
CREATE DATABASE keycloak OWNER keycloak;

-- Nobody but Vigía's roles connects to its database.
REVOKE ALL ON DATABASE vigia FROM PUBLIC;
GRANT CONNECT ON DATABASE vigia TO vigia_app;
REVOKE ALL ON DATABASE keycloak FROM PUBLIC;

\connect vigia
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS postgis;
-- In PG15+ public is no longer writable by PUBLIC; we make it explicit.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
