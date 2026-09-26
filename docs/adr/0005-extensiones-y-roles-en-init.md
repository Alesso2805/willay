# ADR-0005: Extensiones y roles de BD en el init de Postgres, no en Alembic

- **Estado:** Propuesto (borrador de Sprint 0)
- **Fecha:** 2026-09-26
- **Relacionado:** SPEC.md › Roles de base de datos; VIG-02, VIG-03; `infra/postgres/init/01-init.sh`

## Contexto

El plan original ponía extensiones y roles en la migración inicial, pero también exigía que las migraciones corrieran con `vigia_owner`, un rol sin privilegios de superusuario. Las dos cosas son incompatibles:

- `timescaledb` y `postgis` **no son extensiones *trusted***: `CREATE EXTENSION` exige superusuario.
- Un rol no puede crearse a sí mismo, y darle `CREATEROLE` a `vigia_owner` le permitiría crear roles arbitrarios.

## Opciones

1. **Correr Alembic como superusuario.** Todo en una migración, pero el contenedor `migrate` tendría la credencial más poderosa.
2. **Dar `CREATEROLE` a `vigia_owner`** y crear las extensiones de otra forma.
3. **Script de init de Postgres**, que corre como superusuario una sola vez, sobre un volumen vacío.

## Decisión

Opción 3. `infra/postgres/init/01-init.sh`:

- crea los roles `vigia_owner`, `vigia_app` y `keycloak`, con contraseñas desde variables de entorno;
- crea las bases `vigia` (dueño `vigia_owner`) y `keycloak` (dueño `keycloak`);
- revoca `CONNECT` de `PUBLIC` en ambas bases;
- crea las extensiones `timescaledb` y `postgis` en `vigia`.

La migración `0001` hace `CREATE EXTENSION IF NOT EXISTS` como **comprobación**: si la extensión existe, no hace nada; si falta, falla por permisos y `migrate` termina con error, lo que impide arrancar la API y los workers.

La migración `0001` fija además `ALTER DEFAULT PRIVILEGES FOR ROLE vigia_owner` **antes** de crear cualquier tabla. Así las 20 tablas iniciales y las de migraciones futuras reciben sus permisos para `vigia_app` por el mismo mecanismo, y el test de "tabla futura" prueba el camino que usa todo el esquema.

## Consecuencias

- **A favor:** `migrate` solo tiene la credencial de `vigia_owner`. La API y los workers solo tienen la de `vigia_app`.
- **A favor:** los tests de integración montan el mismo script en el contenedor de testcontainers, así prueban exactamente los permisos de producción.
- **En contra:** el init solo corre con el volumen vacío. Cambiar roles o extensiones en una base existente exige un runbook manual. Para desarrollo basta `docker compose down -v`.
- **En contra:** en un Postgres gestionado (Timescale Cloud, por ejemplo) este script no se ejecuta, y su contenido debe aplicarlo quien administre la instancia. Irá en `docs/runbooks/`.
- **Nota:** el script debe tener finales de línea LF (`.gitattributes`) y permiso de ejecución en git, o el entrypoint lo carga con `source` en lugar de ejecutarlo.
