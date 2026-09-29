# Changelog

Todos los cambios visibles se documentan aquí. Formato [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versionado [SemVer](https://semver.org/lang/es/).

## [Unreleased]

### Added
- Monorepo con backend Python (`vigia`), dashboard Angular 22, Makefile y CI en GitHub Actions (VIG-01).
- Stack de Docker Compose: Postgres (TimescaleDB + PostGIS), Keycloak 26.7 con el realm `vigia` y 2 organizaciones, Mailpit, contenedor `migrate`, API, 5 workers y dashboard, con healthchecks (VIG-02).
- Migraciones iniciales: esquemas `core` e `ingest`, 20 tablas, hypertable de lecturas con compresión y retención, roles `vigia_owner` y `vigia_app` con tablas append-only (VIG-03).
- `make seed`: datos demo del Rímac y organización de aislamiento, con API keys de estación Argon2id (VIG-04).
- ADR-0001 a ADR-0006 (VIG-05).
- Login OIDC en el panel con Keycloak y `GET /v1/me`; los tokens con cero o varias organizaciones reciben 403 (VIG-06).
- Matriz de permisos por rol aplicada por endpoint (VIG-07).
- `POST /v1/readings`: lotes de hasta 500 lecturas autenticados con la API key de la estación, límite de 60 lotes por minuto (VIG-08).
- Lecturas tardías (> 1 h) guardadas sin evaluar y aviso inmediato al evaluador (VIG-09).
- Latido de cada estación con su último valor y la hora de medición (VIG-10).
- Simulador de estaciones `make simulate` con el escenario de demo del Rímac (VIG-11).
- Contrato OpenAPI versionado en `docs/openapi.json`.
- Zonas de riesgo: CRUD con validación de geometría y auditoría, y dibujo y edición de polígonos en el mapa del panel (VIG-12).
- Estaciones: CRUD con su posición en cada zona, rotación de API key mostrada una sola vez y página en el panel (VIG-13).
- Worker evaluador: toma lecturas de la cola con `SKIP LOCKED`, despierta con `LISTEN/NOTIFY` y marca como fallida una lectura tras 5 intentos (VIG-14).
- Reglas de umbral e incidentes sin duplicados, con copia de las lecturas que los dispararon (VIG-15).
- Reglas de tasa de cambio, medidas del pico al valle dentro de la ventana (VIG-16).
- Worker `silence`: un incidente por estación que deja de reportar, registro de su recuperación y purga del rate limit (VIG-17).
- Enfriamiento tras resolver un incidente y lecturas que lo agravan en su línea de tiempo (VIG-18).
- API de incidentes: lista, detalle con línea de tiempo, confirmar y resolver (VIG-19).
- Alertas por correo al abrir un incidente, con reintentos, hora local y enlace de confirmación; visibles en Mailpit (VIG-20).
