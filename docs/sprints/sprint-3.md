# Sprint 3 — Silencio detectado, incidentes sin duplicados y primer correo (VIG-17 a VIG-20)

**Estado al 2026-09-29:** las 4 historias (16 puntos) están terminadas, fusionadas en `main` con CI en verde y verificadas contra el stack real. El plan las ubicaba entre el 9 y el 22 de noviembre, así que seguimos adelantados.

## Qué se entregó

| Historia | PR | Resultado | Verificación en el stack real |
| --- | --- | --- | --- |
| VIG-17 | #8 | Worker `silence` cada 15 s: un incidente por estación callada, `station_recovered` una sola vez (migración 0005) y purga del rate limit | RIM-SEU-01 abrió su incidente 35,4 s después de su último latido (límite: 60 s); las 3 estaciones de una regla de zona abrieron uno cada una; RIM-003, que nunca reportó, no alertó |
| VIG-18 | #9 | Enfriamiento para todos los tipos de regla, `reading_added` solo si la lectura agrava el incidente, carrera de dos evaluadores | Un silencio resuelto no se reabrió durante el enfriamiento; el incidente de caída de RIM-CHA-01 registró solo sus nuevos mínimos |
| VIG-19 | #10 | API de incidentes: lista, detalle con línea de tiempo, confirmar (responder en adelante) y resolver (operator en adelante); 409 en transiciones inválidas | Con un token real de Keycloak: confirmar, resolver sin confirmar y 409 al repetir |
| VIG-20 | #11 | Alertas del nivel 1 al abrir un incidente y worker `dispatcher` de correo con reintentos, hora local y enlace de confirmación (migración 0006) | El correo llegó a Mailpit 0,04 s después de recibirse la lectura (objetivo p95: 30 s) |

## Decisiones del sprint

- **Silencio:** una estación que nunca reportó no cuenta como silenciosa, y `station_recovered` lo registra el worker `silence`, no la ingesta.
- **Unicidad en la base:** "una sola vez" (incidente activo, recuperación) la garantiza un índice único parcial, no un "insertar si no existe" con carrera.
- **`reading_added`:** solo entran las lecturas que empeoran el valor disparador; reprocesar una lectura no duplica eventos.
- **Ciclo de vida:** un incidente abierto se puede resolver sin confirmarlo antes; `resolved` es final.
- **Correo:** texto plano con la hora local de la organización; reintentos a los 5, 10 y 20 s; la línea de tiempo nunca guarda el correo ni el `chat_id`.
- **Confirmación:** el enlace abre una página de la API sin login con un botón (POST). Abrirlo nunca confirma, porque los escáneres de correo abren los enlaces solos.

## Retomar

```bash
git switch main
make up && make seed
make lint test
make simulate ARGS="--scenario rimac --seed 42"   # caída en RIM-CHA-01 y, 4 min después, silencio en RIM-SEU-01
```

Los correos de alerta se ven en Mailpit: http://localhost:8025.

## Cambios a SPEC.md y CLAUDE.md en este sprint

- `c753099` docs(spec): silence ignores stations that never reported (PR #8)
- `23c3f5a` docs(spec): reading_added only when the trigger value worsens (PR #9)
- `7c531e3` docs(spec): an open incident can be resolved without acknowledging (PR #10)
- `db11f26` docs(spec): email content, retry timing and a confirmation page (PR #11)

## Pendientes

- [ ] El enlace de confirmación de los correos responde 404 hasta VIG-23, que trae la página y el POST.
- [ ] Las alertas de Telegram se crean pero quedan pendientes hasta VIG-22.
- [ ] Un nivel sin ningún envío debe escalar de inmediato (VIG-24).
- [ ] Decidir con VIG-23/24 si una alerta pendiente se sigue enviando cuando el incidente ya fue confirmado.
- [ ] De sprints anteriores: aceptar los ADR 0001–0006; mostrar el nombre de la organización en `/v1/me` y en el panel; Node 24 en WSL y mover el repo al sistema de archivos de WSL; decidir si se borran `refs/backup/*` y las ramas locales `feat/VIG-01` a `feat/VIG-11`.

## Retro

- **Bien:** preguntar las decisiones de producto antes de cada historia, con una opción recomendada, mantuvo el ritmo. Las pruebas en vivo encontraron un hueco real (un silencio resuelto se reabría) que VIG-18 cerró, y dos textos mal redactados.
- **Mejorar:** en VIG-18 prometí tres commits pero los separé al final, reconstruyendo un estado intermedio. Hay que commitear cada parte en cuanto pasan sus tests.
- **Probar:** en el Sprint 4, además de las mutaciones, registrar los mutantes equivalentes como el del filtro de tenant, que el rollback de la petición neutraliza. Documentan defensas en profundidad que ningún test puede ver.
