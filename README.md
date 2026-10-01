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

Antes del primer `make up`, comprueba dentro de WSL que `docker info` y `make --version` responden. También deben estar libres los puertos de `.env`: 5433 (Postgres), 8080 (Keycloak), 8000 (API), 4200 (panel) y 8025 (Mailpit). Si otro proyecto ocupa alguno, los contenedores de Vigía quedan en `Created` y `make up` falla.

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

Con los datos del seed, Vigía abre incidentes y avisa: `rise` dispara la regla de umbral de RIM-CHO-01, y `rimac`, la caída de caudal de RIM-CHA-01 y, 4 minutos después, el silencio de RIM-SEU-01.

La política del Rímac tiene 3 niveles:
- Nivel 1: correo a Óscar.
- Nivel 2, si nadie confirma en 2 min: correo y Telegram a la Brigada Chosica.
- Nivel 3, 3 min después: Jefatura COE.

Confirmar cualquier alerta, sea con el enlace del correo o con el botón de Telegram, detiene el escalamiento. Los correos se ven en Mailpit (http://localhost:8025).

Una causa recién resuelta o confirmada no vuelve a abrir incidente mientras siga activa ni durante su enfriamiento (30 min en el seed). Para repetir el escenario de inmediato, empieza desde una base vacía (`docker compose down -v`, `make up` y `make seed`).

## Alertas por Telegram (opcional)

Sin bot, el worker `telegram` arranca deshabilitado y las alertas de Telegram quedan pendientes; el correo funciona igual. Para activarlo:

1. Crea un bot con [@BotFather](https://t.me/BotFather) (`/newbot`).
2. Pon su token y su usuario (sin `@`) en `.env`: `VIGIA_TELEGRAM_BOT_TOKEN` y `VIGIA_TELEGRAM_BOT_USERNAME`. El token es un secreto: nunca va al repositorio.
3. Ejecuta `make up` para que la API y los workers lo lean.
4. Genera el enlace de un contacto como admin y ábrelo en Telegram. El ejemplo es para Rosa Brigada, del nivel 2 del seed; el panel tendrá un botón para esto con VIG-36.

```bash
JWT=$(curl -s http://localhost:8080/realms/vigia/protocol/openid-connect/token \
  -d grant_type=password -d client_id=vigia-dev-cli -d username=rimac-admin \
  --data-urlencode "password=$(grep '^VIGIA_DEV_USER_PASSWORD=' .env | cut -d= -f2-)" \
  --data-urlencode 'scope=openid organization:*' \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')
curl -s -X POST -H "Authorization: Bearer $JWT" \
  http://localhost:8000/v1/contacts/01a0dc43-cd2d-7522-8430-8819717232b6/telegram-link
```

El enlace vale 7 días y se usa una sola vez; uno nuevo anula el anterior. Solo la persona que recibió una alerta puede confirmarla con su botón.

## Estructura

| Carpeta | Contenido |
| --- | --- |
| `backend/` | Paquete Python `vigia`: API FastAPI, workers, migraciones Alembic y tests |
| `dashboard/` | Panel Angular |
| `infra/` | Realm de Keycloak y scripts de init de Postgres |
| `docs/` | SPEC, ADR, entrevistas, sprints y runbooks |
