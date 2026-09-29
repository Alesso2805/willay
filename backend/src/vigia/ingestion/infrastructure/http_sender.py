"""Envío de lecturas simuladas a POST /v1/readings, como lo haría una estación real."""

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
            # Una estación real reintentaría en su próximo ciclo; el simulador sigue igual.
            # Nunca se registra la clave: solo el tipo de error.
            log.warning("simulator_send_failed", error=type(exc).__name__)
            return 0
        return response.status_code
