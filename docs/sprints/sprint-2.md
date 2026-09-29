# Sprint 2 — Zonas, estaciones, evaluador confiable y reglas de umbral y tasa de cambio (VIG-12 a VIG-16)

**Estado al 2026-09-29:** las 5 historias (23 puntos) están terminadas, fusionadas en `main` con CI en verde y verificadas contra el stack real. El plan las ubicaba entre el 26 de octubre y el 8 de noviembre, así que vamos adelantados.

## Qué se entregó

| Historia | PR | Resultado | Verificación en el stack real |
| --- | --- | --- | --- |
| VIG-12 | #2 | CRUD de zonas con validación PostGIS (422 con el motivo, nunca `ST_MakeValid`) y auditoría; mapa con dibujo y edición de polígonos (Leaflet-Geoman) | Zona creada, editada y vista como `viewer` en el navegador |
| VIG-13 | #3 | CRUD de estaciones con su posición en cada zona; rotación de API key mostrada una sola vez; estaciones sin zona marcadas | Estación creada y clave rotada en el navegador; la clave anterior deja de valer al instante |
| VIG-14 | #4 | Worker `evaluator` con `SKIP LOCKED`, visibility timeout de 60 s, `LISTEN/NOTIFY` y polling de respaldo de 5 s; `failed_at` al quinto intento | Vació 98 filas pendientes; de la recepción a `evaluated_at`, 12 ms de media y 22 ms de máximo |
| VIG-15 | #5 | Reglas de umbral e incidentes sin duplicados con copia de las lecturas como evidencia | Escenario `rise`: un solo incidente en RIM-CHO-01 con evidencia `[3.556, 3.641]` |
| VIG-16 | #6 | Reglas de tasa de cambio medidas del pico al valle, con la ventana completa como evidencia | Escenario `rimac`: un incidente `critical` en RIM-CHA-01 13 ms después de recibir la lectura de la caída |

Además, el PR #1 dejó el CI en verde en GitHub: `setup-uv` fijado por SHA y una caché separada para el job del stack completo. Desde este sprint cada historia va en su propio PR y el CI la valida antes de fusionarla.

## Decisiones del sprint

- **Geometrías:** un polígono inválido se rechaza con 422 y el motivo de PostGIS; nunca se "arregla" en silencio.
- **Borrado:** `DELETE` desactiva (`is_active = false`) y `PUT` reactiva. Los recursos de otra organización responden 404, no 403.
- **Estaciones:** la unidad es fija por variable, el código no cambia y una clave rotada deja de valer al instante.
- **Incidentes:** la apertura básica se adelantó a VIG-15 y VIG-16. VIG-18 conserva el enfriamiento, los eventos `reading_added` y el test de carrera.
- **Tasa de cambio:** se mide del pico al valle respetando el orden. La ventana termina en la lectura evaluada y ambos extremos están incluidos.
- **Historial:** se reescribió para quitar el trailer de coautoría de Claude. Todos los SHAs cambiaron y las notas de sprint anteriores ya apuntan a los nuevos.

## Retomar

```bash
git switch main
make up && make seed
make lint test
make simulate ARGS="--scenario rimac --seed 42"   # abre el incidente de caída en RIM-CHA-01
```

## Cambios a SPEC.md y CLAUDE.md en este sprint

- `0517a1b` docs(spec): station unit per variable, fixed code, immediate key rotation
- `f723e5b` docs(spec): define how threshold and rate-of-change rules are measured

## Pendientes

- [ ] Aceptar los ADR 0001–0006.
- [ ] Mostrar el nombre de la organización (no su uuid) en `/v1/me` y en el panel.
- [ ] Node 24 en WSL y mover el repo al sistema de archivos de WSL.
- [ ] Decidir si se borran las referencias de respaldo `refs/backup/*` y las ramas locales `feat/VIG-01` a `feat/VIG-11`, que guardan los commits anteriores a la reescritura.
- [ ] Los PR #1 a #4 siguen mostrando los commits viejos en su pestaña "Commits"; solo el soporte de GitHub puede borrarlos.

## Retro

- **Bien:** un PR por historia con CI de tres jobs validó cada entrega, y las pruebas en vivo midieron latencias reales (13 ms de la lectura al incidente). Romper la consulta a propósito confirmó que los tests de la ventana detectan los errores.
- **Mejorar:** reescribir el historial para quitar la atribución costó tiempo y rompió referencias en las notas. Configurarla desde el primer commit lo habría evitado. Docker Desktop apagado también frenó los tests de integración.
- **Probar:** en las notas de sprint, citar cada cambio también por su PR, porque el número de PR sobrevive a una reescritura del historial.
