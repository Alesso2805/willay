"""`GET /v1/events`: eventos en vivo de la organización por SSE (VIG-25).

El JWT va en el header `Authorization`, nunca en la URL (SPEC): el panel usa la librería
`eventsource`, que permite enviarlo.

- Al conectar llega `ready`: el panel pide su estado por REST y desde ahí aplica cambios.
  Así una reconexión nunca deja huecos.
- El stream se cierra cuando vence el token. El cliente se reconecta solo, con un token
  vigente: un token revocado o vencido no mantiene abierto el canal.
- Sin eventos, FastAPI manda un comentario de keepalive cada 15 s (proxies, balanceadores).
"""

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from vigia.identity.api.dependencies import StreamGrantDep
from vigia.realtime.application.broadcaster import Broadcaster
from vigia.shared.web import ClockDep

router = APIRouter(prefix="/v1", tags=["realtime"])

# Espera antes de reconectar, en milisegundos: corta para que el panel no quede ciego.
RETRY_MS = 2000


@router.get(
    "/events",
    response_class=EventSourceResponse,
    summary="Eventos en vivo de la organización (SSE)",
    responses={
        401: {"description": "Token ausente o inválido"},
        403: {"description": "Sin acceso"},
    },
)
async def events(
    request: Request, grant: StreamGrantDep, clock: ClockDep
) -> AsyncIterator[ServerSentEvent]:
    broadcaster: Broadcaster = request.app.state.broadcaster
    with broadcaster.subscribe(grant.principal.organization_id) as subscription:
        yield ServerSentEvent(event="ready", data={}, retry=RETRY_MS)
        while True:
            remaining = (grant.expires_at - clock.now()).total_seconds()
            if remaining <= 0:
                return  # el cliente se reconecta con un token vigente
            try:
                event = await asyncio.wait_for(subscription.next(), timeout=remaining)
            except TimeoutError:
                return
            yield ServerSentEvent(event=event.type, data=dict(event.data))
