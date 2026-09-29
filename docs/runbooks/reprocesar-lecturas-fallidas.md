# Reprocesar lecturas que fallaron en el evaluador

Una lectura queda con `failed_at` cuando el evaluador falló 5 veces al evaluarla (ADR-0002). Sale de la cola para no bloquearla, pero **no se evaluó**: si disparaba una regla, esa alerta no salió. Hay que revisar la causa y reprocesarla.

## 1. Ver qué falló y por qué

```bash
docker compose exec postgres psql -U postgres -d vigia -c "
  SELECT q.id, s.code, q.measured_at, q.attempts, q.failed_at, q.last_error
  FROM ingest.evaluation_queue q JOIN core.stations s ON s.id = q.station_id
  WHERE q.failed_at IS NOT NULL
  ORDER BY q.failed_at DESC;"
```

`last_error` trae la excepción del último intento. Si dice `sin completar tras 5 intentos`, el worker murió durante el último intento (reinicios, memoria, despliegues) y no hubo error de la regla.

## 2. Corregir la causa

- **Error en una regla** (p. ej. parámetros incoherentes): corregir la regla desde el panel o desplegar el arreglo del evaluador.
- **Base o red caídas** durante los 5 intentos: basta con reprocesar.

No reprocesar sin corregir: volverá a fallar 5 veces.

## 3. Devolver las filas a la cola

Reinicia los intentos y las deja disponibles al instante. El evaluador las toma en su próxima consulta (≤ 5 s):

```bash
docker compose exec postgres psql -U postgres -d vigia -c "
  UPDATE ingest.evaluation_queue
  SET failed_at = NULL, attempts = 0, available_at = now(),
      last_error = 'reprocesada a mano: ' || coalesce(last_error, '')
  WHERE failed_at IS NOT NULL
    AND id IN (/* ids del paso 1 */);
  NOTIFY vigia_evaluation_queue;"
```

`NOTIFY` despierta al evaluador sin esperar la consulta periódica.

## 4. Verificar

La fila desaparece de la cola y la lectura tiene `evaluated_at`:

```bash
docker compose exec postgres psql -U postgres -d vigia -c "
  SELECT count(*) AS pendientes FROM ingest.evaluation_queue WHERE failed_at IS NULL;
  SELECT count(*) AS sin_evaluar_120s FROM ingest.readings
  WHERE quality = 'ok' AND evaluated_at IS NULL AND received_at < now() - interval '120 seconds';"
```

La segunda consulta es la NFR de fiabilidad de SPEC: debe dar 0 cuando no hay fallos pendientes.
