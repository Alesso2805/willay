# ADR-0007: Eventos en vivo emitidos por triggers de Postgres

- **Estado:** Propuesto
- **Fecha:** 2026-09-30
- **Relacionado:** SPEC.md › Arquitectura › Tiempo real hacia el panel; VIG-25; ADR-0002

## Contexto

El mapa en vivo (VIG-25) necesita enterarse, en menos de 2 s, de cada cambio en un incidente y de cada latido de estación. SPEC fija el camino: `NOTIFY vigia_events` con la organización, una conexión `LISTEN` en la API y SSE por organización hacia el panel.

Hoy los eventos de incidente se insertan con SQL en diez lugares, repartidos en cinco archivos de dos módulos (incidentes y alertas). Los latidos los escribe la ingesta.

## Opciones

1. **`NOTIFY` en cada lugar que inserta.** Es explícito, pero frágil: cada código nuevo que registre un evento tiene que acordarse de avisar. Si lo olvida, el panel queda desactualizado sin que nada falle ni ningún test lo note.
2. **Un `NOTIFY` en un repositorio común.** Exige que todos los caminos pasen por ese repositorio. Hoy no lo hacen: los inserts viven en SQL de cada módulo, a veces dentro de un `INSERT ... SELECT`.
3. **Triggers `AFTER INSERT`/`AFTER UPDATE` en `core.incident_events` e `ingest.station_heartbeats`.**

## Decisión

Opción 3, en la migración `0008`:

- `core.incident_events`: tras cada `INSERT`, un trigger avisa con `{organization_id, type: "incident", incident_id, event}`. Como todo cambio de estado de un incidente (apertura, escalamiento, confirmación, resolución) deja un evento en la línea de tiempo, alcanza con esta tabla.
- `ingest.station_heartbeats`: tras cada `INSERT` o `UPDATE`, otro trigger avisa con `{organization_id, type: "station", station_id, last_seen_at, last_measured_at, last_value}`. La organización se busca en `core.stations` por su PK, porque la tabla de latidos no la guarda.
- El aviso lleva lo justo para enrutarlo y saber qué refrescar. **Nunca datos personales.** El panel pide el detalle por REST, donde se aplican los permisos y la serialización por rol.
- En la API, una sola conexión `LISTEN` por proceso reparte los avisos en memoria: solo a las conexiones SSE de esa organización, cada una con su cola acotada. Si un cliente se atrasa, o se pierde la conexión con la base, recibe `resync` y el panel vuelve a pedir todo.
- El stream SSE se autentica en una transacción corta y se cierra al vencer el token, para que un panel abierto no retenga una conexión del pool ni sobreviva a su token.

## Consecuencias

- Ningún camino de código, actual o futuro, puede olvidarse de avisar. El aviso sale en la misma transacción que el cambio, y Postgres solo lo entrega si esa transacción confirma: nunca se anuncia algo que terminó en rollback.
- Parte del comportamiento vive en la base y no se ve leyendo Python. Lo compensan esta ADR, el comentario de `shared/notifications.py` y un test de integración que comprueba los avisos con el flujo real de ingesta y evaluación.
- Un latido por lote y estación genera un aviso. Con la carga de VIG-29 (50 estaciones cada 10 s) son unos 5 avisos por segundo, holgados para `NOTIFY`.
- `NOTIFY` no es duradero (ADR-0002): un aviso emitido mientras la API no escucha se pierde. Por eso la reconexión dispara `resync`, y el panel siempre pide su estado al recibir `ready`.
- Si un día los eventos salen de Postgres (ver criterios de ADR-0002), los triggers se reemplazan por un outbox y el contrato hacia el panel (`ready`, `incident`, `station`, `resync`) no cambia.
