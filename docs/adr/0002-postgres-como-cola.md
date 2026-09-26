# ADR-0002: PostgreSQL como cola, canal de notificaciones y rate limit

- **Estado:** Propuesto (borrador de Sprint 0)
- **Fecha:** 2026-09-26
- **Relacionado:** SPEC.md › Arquitectura (Garantía de no pérdida, Rate limit); VIG-08, VIG-09, VIG-14

## Contexto

En un sistema de alertas, una alerta perdida es peor que una duplicada. Cada lectura aceptada debe evaluarse, aunque un worker se caiga a mitad de camino. La meta de latencia es p95 < 30 s de lectura a alerta. La carga del MVP es modesta: 50 estaciones a una lectura cada 10 s son 5 lecturas por segundo.

Las opciones habituales (Redis, RabbitMQ, Kafka) añaden un servicio que operar y, sobre todo, un problema de consistencia: guardar la lectura en Postgres y publicarla en un broker son dos escrituras que pueden quedar a medias. Resolverlo exige el patrón outbox.

## Opciones

1. **Redis Streams o RabbitMQ**, con outbox para no perder mensajes.
2. **Kafka**: sobredimensionado para 5 mensajes por segundo.
3. **Postgres**: tabla `ingest.evaluation_queue` con `FOR UPDATE SKIP LOCKED`, `LISTEN/NOTIFY` para despertar a los workers y una tabla de ventanas para el rate limit.

## Decisión

Opción 3, detrás de una interfaz `EvaluationQueue` para poder cambiarla sin tocar el dominio.

- **Encolado atómico:** la lectura y su fila en `evaluation_queue` se insertan en la **misma transacción**. No hace falta outbox.
- **Dos transacciones por fila en el evaluador:**
  1. Una transacción corta toma la fila (`available_at <= now`, `SKIP LOCKED`), incrementa `attempts`, fija `available_at = now + 60 s` (visibility timeout) y confirma. El contador sobrevive aunque el worker muera.
  2. Otra transacción evalúa, escribe incidentes y alertas, marca `readings.evaluated_at` y borra la fila. Si el worker muere aquí, todo se revierte y la fila reaparece al vencer el timeout.
- **Filas envenenadas:** con `attempts >= 5` se marca `failed_at`. La fila sale del índice parcial (`WHERE failed_at IS NULL`) y el operador la ve en el panel. Un runbook documentará cómo reprocesarla.
- **Despertar:** `NOTIFY` al encolar y al crear alertas. Como `NOTIFY` no es duradero (si nadie escucha, se pierde), los workers consultan la cola cada 5 s como respaldo.
- **Rate limit:** `ingest.rate_limit_windows` con un contador por estación y minuto, actualizado con un upsert atómico. Funciona con varias réplicas de la API. El worker `silence` purga las ventanas de más de 1 h.
- **Idempotencia:** `UNIQUE (station_id, measured_at)` en la cola y la PK de `readings` impiden procesar dos veces la misma lectura.

## Consecuencias

- **A favor:** un servicio menos. Garantía de no pérdida con una sola transacción. Todo el estado es consultable con SQL, por ejemplo "cero lecturas `ok` sin `evaluated_at` pasados 120 s", con su índice parcial.
- **En contra:** el visibility timeout fija un piso de reintento de 60 s. Una evaluación que tarde más que eso podría ejecutarse dos veces, y la idempotencia de incidentes (índice único de `dedup_key`) lo cubre.
- **En contra:** la cola compite con el resto de la carga de Postgres, y `LISTEN` ocupa una conexión dedicada por proceso.
- **Criterios para migrar a Redis Streams o Kafka:**
  - p95 de toma de una fila > 1 s de forma sostenida;
  - más de ~500 lecturas por segundo;
  - bloat de la tabla de cola que el autovacuum no controle;
  - necesidad de varios consumidores independientes del mismo evento.
