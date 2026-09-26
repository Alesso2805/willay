# Sprint 0 — Fundaciones (VIG-01 a VIG-05)

**Estado al 2026-09-26:** historias terminadas y verificadas en local. Falta CI en GitHub (no hay remoto).

## Dónde quedó el código

Las ramas están **apiladas**: cada una parte de la anterior. `main` solo tiene los commits `docs(spec)`.

```
main → feat/VIG-01-monorepo-ci → feat/VIG-02-docker-compose
     → feat/VIG-03-initial-migration → feat/VIG-04-seed → feat/VIG-05-adrs  (la más reciente)
```

Para retomar: `git checkout feat/VIG-05-adrs`. `git log --oneline main..HEAD` lista los 8 commits del sprint.

## Verificación rápida (desde WSL)

```bash
make up         # 11 servicios: todo healthy y migrate en Exited (0)
make seed       # claves en .secrets/station-keys.json
make lint test  # Ruff, Mypy, ESLint; Pytest (37) y Vitest (3)
make down       # al terminar
```

## Pendientes antes del Sprint 1

- [ ] Crear el repo en GitHub, hacer push y fusionar las ramas en orden (o abrir un PR por historia). Confirmar CI en verde.
- [ ] Decidir si se alinea CLAUDE.md con SPEC: el claim `organization` es un objeto `{alias: {id}}`, y los roles y las extensiones viven en el init de Postgres.
- [ ] Revisar los ADR 0001–0006 y pasarlos a "Aceptado".
- [ ] Instalar Node 24 en WSL (`nvm install` lee `dashboard/.nvmrc`).

## Siguiente paso

Planificar el Sprint 1 empezando por **VIG-06** (login OIDC y resolución del tenant con 403 para cero o varias organizaciones). En paralelo, **VIG-08** (`POST /v1/readings`), que ya tiene el formato y el hash de las API keys en `ingestion/infrastructure/api_keys.py`.

## Cambios a SPEC.md en este sprint

`50c95fe`, `0ebabac`, `c82fca8`, `00eafff`, `f778a32` (ver `git log -- docs/SPEC.md`).

## Retro

- **Bien:** verificar contra el stack real destapó a tiempo tres supuestos falsos: el formato del claim, los scopes por defecto de Keycloak y el orden de los privilegios.
- **Mejorar:** trabajar en `/mnt/c` desde Windows causó problemas de CRLF y de conversión de rutas. Conviene clonar el repo dentro de WSL.
- **Probar:** abrir un PR por historia en cuanto exista el remoto, en vez de apilar ramas.
