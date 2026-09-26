# Changelog

Todos los cambios visibles se documentan aquí. Formato [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versionado [SemVer](https://semver.org/lang/es/).

## [Unreleased]

### Added
- Monorepo con backend Python (`vigia`), dashboard Angular 22, Makefile y CI en GitHub Actions (VIG-01).
- Stack de Docker Compose: Postgres (TimescaleDB + PostGIS), Keycloak 26.7 con el realm `vigia` y 2 organizaciones, Mailpit, contenedor `migrate`, API, 5 workers y dashboard, con healthchecks (VIG-02).
- Migraciones iniciales: esquemas `core` e `ingest`, 20 tablas, hypertable de lecturas con compresión y retención, roles `vigia_owner` y `vigia_app` con tablas append-only (VIG-03).
- `make seed`: datos demo del Rímac y organización de aislamiento, con API keys de estación Argon2id (VIG-04).
- ADR-0001 a ADR-0006 (VIG-05).
