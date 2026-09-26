#!/usr/bin/env bash
# Corre como superusuario una sola vez, cuando el volumen de datos está vacío.
# Crea lo que una migración con vigia_owner no puede crear (ADR-0005):
#   - roles vigia_owner, vigia_app y keycloak (un rol no puede crearse a sí mismo)
#   - bases vigia y keycloak
#   - extensiones timescaledb y postgis (no son "trusted": exigen superusuario)
set -euo pipefail

: "${VIGIA_OWNER_PASSWORD:?falta VIGIA_OWNER_PASSWORD}"
: "${VIGIA_APP_PASSWORD:?falta VIGIA_APP_PASSWORD}"
: "${KEYCLOAK_DB_PASSWORD:?falta KEYCLOAK_DB_PASSWORD}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v owner_pw="$VIGIA_OWNER_PASSWORD" \
  -v app_pw="$VIGIA_APP_PASSWORD" \
  -v kc_pw="$KEYCLOAK_DB_PASSWORD" <<'SQL'
CREATE ROLE vigia_owner LOGIN PASSWORD :'owner_pw';
CREATE ROLE vigia_app LOGIN PASSWORD :'app_pw';
CREATE ROLE keycloak LOGIN PASSWORD :'kc_pw';

CREATE DATABASE vigia OWNER vigia_owner;
CREATE DATABASE keycloak OWNER keycloak;

-- Nadie más que los roles de Vigía se conecta a su base.
REVOKE ALL ON DATABASE vigia FROM PUBLIC;
GRANT CONNECT ON DATABASE vigia TO vigia_app;
REVOKE ALL ON DATABASE keycloak FROM PUBLIC;

\connect vigia
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS postgis;
-- En PG15+ public ya no es escribible por PUBLIC; lo dejamos explícito.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
