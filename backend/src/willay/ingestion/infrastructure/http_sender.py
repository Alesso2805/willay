"""Sends simulated readings to POST /v1/readings, as a real station would."""

from datetime import datetime

import httpx2
import structlog

log = structlog.get_logger()


class HttpReadingSender:
    def __init__(self, client: httpx2.AsyncClient) -> None:
        self._client = client

    async def send(self, api_key: str, measured_at: datetime, value: float) -> int:
        body = {"readings": [{"measured_at": measured_at.isoformat(), "value": value}]}
        try:
            response = await self._client.post(
                "/v1/readings", json=body, headers={"X-Api-Key": api_key}
            )
        except httpx2.HTTPError as exc:
            # A real station would retry on its next cycle; the simulator just carries on.
            # Never log the API key: only the error type.
            log.warning("simulator_send_failed", error=type(exc).__name__)
            return 0
        return response.status_code
