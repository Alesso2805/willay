"""`GET /v1/events`: the organization's live events over SSE (VIG-25).

The JWT goes in the `Authorization` header, never in the URL (SPEC). On connect the client
gets `ready` and reloads its state over REST, so a reconnect never leaves gaps. The stream
closes when the token expires, so a revoked or expired token cannot keep the channel open.
When idle, FastAPI sends a keepalive comment every 15 s (proxies, load balancers).
"""

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from willay.identity.api.dependencies import StreamGrantDep
from willay.realtime.application.broadcaster import Broadcaster
from willay.shared.web import ClockDep

router = APIRouter(prefix="/v1", tags=["realtime"])

# Reconnect delay in milliseconds: short so the dashboard is never blind for long.
RETRY_MS = 2000


@router.get(
    "/events",
    response_class=EventSourceResponse,
    summary="The organization's live events (SSE)",
    responses={
        401: {"description": "Missing or invalid token"},
        403: {"description": "No access"},
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
                return  # the client reconnects with a valid token
            try:
                event = await asyncio.wait_for(subscription.next(), timeout=remaining)
            except TimeoutError:
                return
            yield ServerSentEvent(event=event.type, data=dict(event.data))
