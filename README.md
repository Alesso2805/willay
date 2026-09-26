# Vigía

Sistema de alerta temprana multi-tenant: ingiere lecturas de sensores, evalúa reglas por zona de riesgo (umbral, tasa de cambio, sensor silencioso), abre incidentes sin duplicados y despacha alertas por correo y Telegram con escalamiento automático si nadie confirma.

> **Herramienta de apoyo.** Vigía ayuda a operadores y líderes comunales a detectar, decidir y avisar. No reemplaza a los sistemas oficiales de alerta a la población (INDECI, COER regionales, SISMATE).

"Vigía" es un nombre de código; el paquete se llama `vigia`. La especificación completa está en [docs/SPEC.md](docs/SPEC.md) y las decisiones técnicas en [docs/adr/](docs/adr/).

## Requisitos

- Windows con **WSL2 (Ubuntu)** o Linux. Todos los comandos se ejecutan dentro de WSL.
- Docker Desktop con la integración WSL activada (o Docker Engine en Linux).
- [uv](https://docs.astral.sh/uv/) para el backend (instala Python 3.12 si falta).
- Node.js 24 LTS para el dashboard (`nvm install` lee `dashboard/.nvmrc`).
- `make`.

Recomendación: clona el repo dentro del sistema de archivos de WSL (por ejemplo `~/code/vigia-project`), no en `/mnt/c`. Los bind mounts y `node_modules` sobre `/mnt/c` son lentos.

## Levantarlo

```bash
cp .env.example .env    # y completa los valores
make up                 # postgres, keycloak, mailpit, migrate, api, 5 workers, dashboard
make seed               # datos demo; imprime las API keys del simulador
```

## Desarrollo

```bash
make help   # lista todos los comandos
make lint   # Ruff, Mypy strict, ESLint
make test   # Pytest (unit + integración con Postgres real vía Docker) y Vitest
```

## Estructura

| Carpeta | Contenido |
| --- | --- |
| `backend/` | Paquete Python `vigia`: API FastAPI, workers, migraciones Alembic y tests |
| `dashboard/` | Panel Angular |
| `infra/` | Realm de Keycloak y scripts de init de Postgres |
| `docs/` | SPEC, ADR, entrevistas, sprints y runbooks |
