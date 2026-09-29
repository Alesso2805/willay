# Sprint 1 — Lecturas autenticadas se encolan de forma atómica por tenant (VIG-06 a VIG-11)

**Estado al 2026-09-29:** las 6 historias terminadas y verificadas contra el stack real, antes de las fechas del plan (12–25 oct). CI en GitHub sigue sin correr: no hay remoto.

## Qué se entregó

| Historia | Resultado | Verificación en el stack real |
| --- | --- | --- |
| VIG-06 | Login OIDC (Code + PKCE, scope `organization:*`), `CurrentPrincipal`, `GET /v1/me`, 403 con cero o varias organizaciones | Login en el navegador con `rimac-operator`; 403 para `sin-org` y `dos-orgs` |
| VIG-07 | Matriz de permisos (SPEC › Permisos por rol) y `require(Permission)` | `/v1/me` devuelve los permisos de cada rol con tokens de Keycloak |
| VIG-08 | `POST /v1/readings` con `X-Api-Key`, lotes de 1 a 500, 60 lotes/min por estación | 70 lotes concurrentes en 2 réplicas: 60 aceptados y 10 con 429 |
| VIG-09 | Lecturas tardías (> 1 h) guardadas sin encolar; `NOTIFY` al evaluador solo tras commit | `LISTEN` recibe el aviso; `"late": 1` en la respuesta |
| VIG-10 | Latido en `station_heartbeats` con `last_measured_at` (migración 0004); nunca retrocede | Latido con el valor más reciente a tiempo, ignorando la tardía |
| VIG-11 | `make simulate` con escenarios normal/rise/drop/silence/rimac, reproducible con semilla | Escenario `rimac` contra la API: caída de 85 a 33 m³/s en el paso del evento |

## Retomar

Rama más reciente: `feat/VIG-11-simulator` (apilada sobre `feat/VIG-01` … `feat/VIG-10`).

```bash
make up && make seed
make lint test
make simulate ARGS="--scenario rimac --seed 42"
```

## Cambios a SPEC.md y CLAUDE.md en este sprint

- `42a19c5` docs: align CLAUDE.md with SPEC on organization claim and DB init
- `b4d1f28` docs(spec): role permission matrix
- `9f9f8f3` docs(spec): add last_measured_at to station heartbeats
- `2ec0f70` docs(spec): use httpx2 as the HTTP client

## Pendientes

- [ ] Crear el remoto en GitHub, hacer push y confirmar CI en verde.
- [ ] Aceptar los ADR 0001–0006.
- [ ] Mostrar el nombre de la organización (no su uuid) en `/v1/me` y en el panel.
- [ ] Node 24 en WSL.

## Retro

- **Bien:** probar contra el stack real y con mutaciones encontró errores que los tests verdes no mostraban: un 500 con `NaN`, un Keycloak sin puerto y una sintaxis SQL.
- **Mejorar:** trabajar desde Windows sobre `/mnt/c` siguió dando fricción (CRLF, rutas de MSYS, Node viejo). Hay que pasar el repo a WSL.
- **Probar:** en el Sprint 2 hay que abrir el remoto y un PR por historia, para que CI valide cada entrega.
