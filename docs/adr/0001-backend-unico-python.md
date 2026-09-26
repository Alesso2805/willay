# ADR-0001: Backend único en Python con módulos y workers separados

- **Estado:** Propuesto (borrador de Sprint 0)
- **Fecha:** 2026-09-26
- **Relacionado:** SPEC.md › Arquitectura; Repositorio, convenciones y documentación viva

## Contexto

Vigía necesita ingesta HTTP, evaluación de reglas, detección de silencio, envío de alertas por dos canales, escalamiento y un canal SSE hacia el panel. Lo construye y mantiene una sola persona fuera de su jornada laboral, en 7 sprints de dos semanas. La fase 3 candidata (modelos predictivos de huaicos) se haría en Python.

Hay procesos con perfiles muy distintos: la API responde en milisegundos, el evaluador consume una cola, el worker de Telegram hace long polling y el de escalamiento corre cada 15 s. Si fallan juntos, una caída del proveedor SMTP podría frenar la evaluación de lecturas.

## Opciones

1. **Tres servicios** (ingesta, reglas/incidentes, alertas) con su propio repositorio o imagen y comunicación por red.
2. **Un monolito** con los workers como tareas dentro del lifespan de FastAPI.
3. **Un solo paquete Python (`vigia`) desplegado como varios procesos**: la API y 5 workers con el mismo código e imagen, ejecutados con `python -m vigia.workers.<nombre>`.

## Decisión

Opción 3. Un paquete `vigia` con módulos `identity`, `ingestion`, `territory`, `rules`, `incidents`, `alerts` y `realtime`. Cada módulo tiene las capas `domain`, `application`, `infrastructure` y `api`, y el dominio no importa FastAPI ni SQLAlchemy. Los esquemas de base de datos `ingest` y `core` marcan el límite entre módulos.

Nunca se ejecutan workers dentro del lifespan de FastAPI. En Docker Compose, una sola imagen (`vigia-backend`) sirve a `api`, `migrate` y los 5 workers, y solo cambia el comando.

## Consecuencias

- **A favor:** un solo `pyproject.toml`, un solo `uv.lock`, un solo pipeline de CI y refactors que cruzan módulos en un commit. Cada proceso escala y falla por separado. `SKIP LOCKED` reparte el trabajo entre réplicas del mismo worker.
- **A favor:** el código de la fase predictiva puede importar el dominio sin una API intermedia.
- **En contra:** los límites entre módulos dependen de disciplina. Mitigación futura: una herramienta de contratos de importación (por ejemplo import-linter) en CI cuando haya código de dominio real.
- **En contra:** los workers no exponen HTTP. Su healthcheck es un archivo de latido que el worker toca en cada ciclo, y `python -m vigia.workers.healthcheck <nombre>` comprueba que tenga menos de 30 s.
- **Salida:** si un módulo necesita separarse, su esquema de base de datos y sus interfaces (por ejemplo `EvaluationQueue`) ya marcan el corte.
