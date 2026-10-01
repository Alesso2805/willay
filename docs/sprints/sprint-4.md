# Sprint 4 — Telegram vinculado, confirmación y escalamiento automático (VIG-21 a VIG-24)

**Estado al 2026-09-30:** las 4 historias (16 puntos) están terminadas, fusionadas en `main` con CI en verde y verificadas contra el stack real, con un bot de Telegram de verdad. El plan las ubicaba entre el 23 de noviembre y el 6 de diciembre. Orden elegido: VIG-23 → 24 → 21 → 22, para probar la confirmación y el escalamiento por correo antes de sumar Telegram. La suite quedó en 572 tests.

## Qué se entregó

| Historia | PR | Resultado | Verificación en el stack real |
| --- | --- | --- | --- |
| VIG-23 | #13 | Página de confirmación servida por la API, sin login: GET solo muestra, POST confirma. El token vale 24 h y se usa una vez. Las alertas pendientes de un incidente ya confirmado o resuelto se omiten con su motivo | Óscar confirmó desde el correo de Mailpit y el incidente de tasa de cambio quedó confirmado en el nivel 1, sin escalar |
| VIG-24 | #14 | Worker `escalation` cada 15 s: sube de nivel al vencer `wait_s`, contado desde que se avisó a ese nivel (migración 0007); un nivel sin ningún envío escala de inmediato. API de políticas para admin | El incidente de silencio escaló al nivel 2 a los 128 s ("nadie confirmó en 120 s"). En la prueba de la historia, el nivel 1 escaló al 2 a los 134 s, una confirmación en el nivel 2 detuvo el escalamiento, y los incidentes previos agotaron su último nivel a los 300 s |
| VIG-21 | #15 | Enlace `t.me/<bot>?start=<token>` de un solo uso que vale 7 días; el worker `telegram` guarda el `chat_id` al recibir `/start` | Rosa Brigada quedó vinculada con un bot real; el enlace anterior respondió "no válido", porque uno nuevo invalida el anterior |
| VIG-22 | #16 | El dispatcher envía por Telegram con un botón cuyo `callback_data` es el token; solo el destinatario puede confirmar; tras el clic el botón se reemplaza por una nota | Telegram salió 1 s después de escalar y se confirmó con el botón 7 s después. El botón desapareció y quedó la nota "Confirmado por Rosa Brigada el 30/09/2026 18:57 (America/Lima)". El Telegram de Lucho, que no lo tiene vinculado, quedó omitido y registrado |

## Decisiones del sprint

- **Confirmación:** confirmar cualquier alerta confirma el incidente. Si otro se adelantó, la alerta queda como vista sin cambiar quién confirmó; si el incidente ya estaba resuelto, no cambia nada.
- **Escalamiento:** `wait_s` cuenta desde que se avisó al nivel (`incidents.level_started_at`). El worker lee la política vigente, así que los cambios de un admin aplican a los incidentes en curso.
- **Telegram:**
  - El admin genera el enlace y se lo comparte al contacto.
  - Solo el chat que recibió la alerta puede confirmarla; a cualquier otro le llega un aviso sin datos del incidente.
  - El token del bot nunca llega a los logs: el logger de httpx2 queda en WARNING y los errores no encadenan la excepción original.
- **Canales independientes:** si Telegram cae, el correo sigue saliendo. Una actualización de Telegram que no se puede leer se descarta y no bloquea a las siguientes.
- **Revisión del backlog (PR #17):**
  - Nuevas historias VIG-33 a VIG-39: sistema visual, bandeja de incidentes, acciones desde el panel, contactos y grupos, políticas en el panel, auditoría y lecturas fallidas.
  - El `chat_id` nunca sale de la API.
  - Se suma un sprint 7.

## Retomar

```bash
git switch main
make up && make seed
make lint test
make simulate ARGS="--scenario rimac --seed 42"
```

Para recibir alertas por Telegram:
1. Crea un bot con @BotFather.
2. Pon `VIGIA_TELEGRAM_BOT_TOKEN` y `VIGIA_TELEGRAM_BOT_USERNAME` (sin `@`) en `.env`.
3. Genera el enlace de un contacto con `POST /v1/contacts/{id}/telegram-link` usando un token de admin (ver README).

Los correos se ven en Mailpit: http://localhost:8025.

## Cambios a SPEC.md y CLAUDE.md en este sprint

- `249eaa0` docs(spec): confirmation outcomes and no alerts after confirmation (PR #13)
- `035bc16` docs(spec): escalation timing and live policies (PR #14)
- `fa5f472` docs(spec): Telegram link lifetime and how it reaches the contact (PR #15)
- `caf4bdb` docs(spec): only the recipient confirms from the Telegram button (PR #16)
- `35d6223` docs(spec): a contact's chat_id never leaves the API (PR #17)
- `8e5847e` docs(spec): add panel and admin stories VIG-33 to VIG-39 with a sprint 7 (PR #17)

## Pendientes

- [ ] **Entrevistas de validación:** SPEC pedía al menos 3 antes del Sprint 4 y ajustar el backlog antes del Sprint 5; `docs/research/` sigue vacía. El Sprint 5 construye el panel, justo lo que más deberían moldear.
- [ ] **Entorno WSL:** activar en Docker Desktop la integración WSL de Ubuntu e instalar `make`. La prueba en vivo se hizo desde Windows porque WSL no tenía ninguno de los dos.
- [ ] **Puertos:** el otro proyecto local (`keycloak_custom` en 8080 y `pgsql_keycloak` en 5433) choca con Vigía y deja sus contenedores en `Created`; hay que detenerlo antes de `make up`. Decidir si se vuelven configurables de punta a punta los puertos de Keycloak, cuya URL también vive en el realm, el panel y la validación de tokens.
- [ ] Al confirmar desde Telegram, el mensaje conserva la línea "Si nadie lo confirma, Vigía avisará al siguiente nivel.", que ya no aplica: quitarla al editar.
- [ ] VIG-30 (`make demo`) necesita reiniciar los datos de la demo sin perder los contactos vinculados: el enfriamiento de 30 min impide repetir el escenario de inmediato.
- [ ] De sprints anteriores:
  - aceptar los ADR 0001–0006;
  - Node 24 en WSL y mover el repo al sistema de archivos de WSL;
  - decidir si se borran `refs/backup/*` y las ramas locales `feat/VIG-01` a `feat/VIG-11`.
  - El nombre de la organización en el panel pasó a VIG-33.

## Retro

- **Bien:** VIG-22 se entregó en dos partes, cada una con commit en cuanto pasaron sus tests, como pedía la retro anterior. La prueba con el bot real funcionó a la primera en el código: los problemas fueron todos del entorno.
- **Mejorar:** la guía de la prueba en vivo dio por hecho un WSL con Docker y `make`, y puertos libres, y no avisó que confirmar el correo del nivel 1 detiene el escalamiento antes de llegar a Telegram. Toda guía de prueba debe empezar con una verificación del entorno.
- **Probar:** en VIG-30, que `make demo` compruebe el entorno (Docker, puertos) y reinicie los datos de la demo antes de lanzar el escenario.
