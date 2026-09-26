# Architecture Decision Records

Una decisión técnica por archivo: contexto, opciones, decisión y consecuencias. Toda decisión no cubierta por [SPEC.md](../SPEC.md) se registra aquí con el siguiente número libre (`NNNN-titulo.md`).

| ADR | Decisión | Estado |
| --- | --- | --- |
| [0001](0001-backend-unico-python.md) | Backend único en Python con módulos y workers separados | Propuesto |
| [0002](0002-postgres-como-cola.md) | PostgreSQL como cola, canal de notificaciones y rate limit | Propuesto |
| [0003](0003-timescaledb-lecturas.md) | TimescaleDB para las lecturas | Propuesto |
| [0004](0004-keycloak-organizations-tenant.md) | Keycloak 26 Organizations como fuente de tenant y roles | Propuesto |
| [0005](0005-extensiones-y-roles-en-init.md) | Extensiones y roles de BD en el init de Postgres | Propuesto |
| [0006](0006-migraciones-sql-y-tests-con-testcontainers.md) | Migraciones en SQL explícito y tests con testcontainers | Propuesto |

Estados: Propuesto → Aceptado → (Reemplazado por ADR-NNNN | Obsoleto).
