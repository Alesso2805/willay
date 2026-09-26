# ADR-0006: Migraciones en SQL explícito y tests de integración con testcontainers

- **Estado:** Propuesto (borrador de Sprint 0)
- **Fecha:** 2026-09-26
- **Relacionado:** SPEC.md › Esquema de base de datos; Definición de hecho; VIG-03

## Contexto

El esquema usa DDL que Alembic no sabe autogenerar: hypertables, políticas de columnstore y retención, geometrías PostGIS, índices únicos parciales, `ALTER DEFAULT PRIVILEGES` y `REVOKE`. Además, la definición de hecho exige tests de integración contra un **Postgres real**, con las extensiones y los roles de producción.

## Decisión

### Migraciones

- Se escriben **a mano con `op.execute()` y SQL explícito**. No hay `target_metadata` ni autogenerate. Los modelos de SQLAlchemy de cada módulo llegarán con sus historias y deberán coincidir con las migraciones, no generarlas.
- **Valores cerrados con `text` + `CHECK`, no con tipos `ENUM`.** Añadir un valor a un `ENUM` es fácil, pero quitarlo o renombrarlo no. Un `CHECK` se reemplaza en una migración normal.
- Una transacción por migración (`transaction_per_migration=True`): si la `0003` falla, la `0001` y la `0002` quedan aplicadas. Esto se vio en la práctica durante VIG-03.
- Revisiones con ids legibles (`0001`, `0002`…) y `downgrade()` en todas. Un test hace `upgrade head` → `downgrade base` → `upgrade head`.
- Las PK uuid v7 **no tienen `DEFAULT`**: las genera la aplicación con `uuid-utils`, porque PostgreSQL 16 no tiene `uuidv7()`.

### Tests de integración

- **testcontainers** levanta por sesión de pytest la **misma imagen** que Docker Compose (`timescale/timescaledb-ha:pg16-ts2.30`) con el **mismo script de init**, y aplica las migraciones con `vigia_owner`.
- Hay fixtures `owner` y `app` (conexiones asyncpg con cada rol), así los tests de permisos usan el rol real de la API.
- Cada test crea su propia organización con uuids nuevos. La base es compartida y no hace falta limpiarla (tampoco se podría en las tablas append-only).
- Alembic se ejecuta en un hilo propio, porque `env.py` usa `asyncio.run()` y pytest-asyncio ya tiene un event loop corriendo.
- El marcador `integration` permite `pytest -m "not integration"` para una pasada rápida sin Docker.

## Consecuencias

- **A favor:** el SQL de la migración es exactamente el que corre en producción, legible y revisable en el PR. Los tests prueban permisos, índices y restricciones reales, no un SQLite ni un mock.
- **En contra:** sin autogenerate no hay detección automática de divergencia entre modelos y esquema. Mitigación: tests de integración que usen los repositorios reales contra la base migrada.
- **En contra:** los tests de integración necesitan Docker. El runner de GitHub Actions lo trae, y el contenedor de sesión añade unos segundos (≈ 8 s la suite completa en local).
