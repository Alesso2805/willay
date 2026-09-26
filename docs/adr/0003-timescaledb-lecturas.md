# ADR-0003: TimescaleDB para las lecturas

- **Estado:** Propuesto (borrador de Sprint 0)
- **Fecha:** 2026-09-26
- **Relacionado:** SPEC.md › Esquema de base de datos (`ingest.readings`); VIG-03

## Contexto

Las lecturas son una serie temporal que solo crece: 50 estaciones a 1 lectura cada 10 s son unos 430 000 filas diarias. Las reglas consultan ventanas recientes por estación (las últimas N lecturas y los últimos T minutos). El detalle de un incidente grafica las lecturas alrededor del evento. Las lecturas viejas pierden valor operativo, pero la línea de tiempo de un incidente debe seguir siendo auditable.

## Opciones

1. **Postgres sin extensiones**, con particionado declarativo a mano y jobs propios de purga.
2. **Una base de series temporales aparte** (InfluxDB, por ejemplo): otro servicio y otra consistencia.
3. **TimescaleDB** sobre el mismo Postgres.

## Decisión

Opción 3. `ingest.readings` es una hypertable particionada por `measured_at`:

- chunks de 1 día;
- **columnstore** (compresión) a los 7 días, con `segmentby = station_id` y `orderby = measured_at DESC`, que coincide con el patrón de consulta "una estación en una ventana";
- retención de 180 días.

Reglas que acompañan esta decisión:

- **Nada apunta con FK a `readings`**, porque Timescale restringe las FK hacia hypertables. `evaluation_queue` guarda `(station_id, measured_at)` sin FK. La FK de `readings` hacia `core.stations` sí está soportada.
- **Evidencia:** el evento `opened` de cada incidente copia en su `payload` las lecturas que dispararon la regla, así la línea de tiempo sobrevive a la retención.
- **`evaluated_at`** permite verificar que ninguna lectura `ok` quedó sin evaluar.

Se usa la API actual de TimescaleDB 2.30: `add_columnstore_policy` y `timescaledb.enable_columnstore`. Los nombres `compression` quedan como alias heredados.

## Consecuencias

- **A favor:** particionado, compresión y retención declarativos en la migración, sin jobs propios. Consultas en SQL normal y una sola base.
- **Condiciona el despliegue:** AWS RDS y Aurora no ofrecen TimescaleDB. Las opciones son Postgres autogestionado (contenedor o VM) o Timescale Cloud. La imagen de referencia es `timescale/timescaledb-ha:pg16-ts2.30`.
- **Licencia:** compresión/columnstore y las políticas de retención están bajo la **Timescale License (TSL)**, no Apache 2.0. La TSL permite usarlas en un producto propio, pero no ofrecer TimescaleDB como servicio de base de datos. Hay que revisarla antes de cualquier uso comercial. Las variantes `-oss` de la imagen no incluyen estas funciones.
- **En contra:** insertar lecturas muy tardías en chunks ya comprimidos es más caro. Las lecturas con más de 1 h de retraso se marcan `late` y no se encolan (VIG-09).
