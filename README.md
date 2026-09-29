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

## Simulador de estaciones

Envía lecturas reales a `POST /v1/readings` con las API keys que dejó `make seed` en `.secrets/station-keys.json`. La misma semilla produce siempre la misma serie de valores. Corre en tiempo real (un lote por estación cada 10 s) porque la detección de silencio mide con el reloj de verdad.

```bash
make simulate ARGS="--scenario normal --stations 3 --seed 7 --steps 12"
make simulate ARGS="--scenario rimac --seed 42"   # demo: caída aguas abajo y, 4 min después, silencio aguas arriba
```

Escenarios: `normal`, `rise` (el valor se duplica en 5 min), `drop` (cae al 40 %), `silence` (deja de reportar) y `rimac`. `--event-after` fija cuándo empieza el evento (60 s por defecto).

Con los datos del seed, Vigía ya abre incidentes y avisa por correo: `rise` dispara la regla de umbral de RIM-CHO-01, y `rimac`, la caída de caudal de RIM-CHA-01 y, 4 minutos después, el silencio de RIM-SEU-01. Los correos del nivel 1 se ven en Mailpit (http://localhost:8025). Una causa recién resuelta no vuelve a abrir incidente durante su enfriamiento (30 min en el seed).

## Estructura

| Carpeta | Contenido |
| --- | --- |
| `backend/` | Paquete Python `vigia`: API FastAPI, workers, migraciones Alembic y tests |
| `dashboard/` | Panel Angular |
| `infra/` | Realm de Keycloak y scripts de init de Postgres |
| `docs/` | SPEC, ADR, entrevistas, sprints y runbooks |
