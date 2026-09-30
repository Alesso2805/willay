"""Confirmar una alerta desde su enlace (VIG-23), sin login: el token es la credencial.

GET muestra la página y no cambia nada (los escáneres de correo abren los enlaces
solos); solo el POST del botón confirma. No hace falta protección CSRF: sin el token no
se puede construir el POST, y no hay sesión ni cookies que otro sitio pueda aprovechar.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from structlog import get_logger

from vigia.alerts.api.pages import render_preview, render_result
from vigia.alerts.application.confirmation import confirm_alert, preview_confirmation
from vigia.alerts.infrastructure.sql_confirmation import SqlConfirmationRepository
from vigia.incidents.infrastructure.incidents_repository import SqlIncidentRepository
from vigia.shared.web import ClockDep, DbConnection

router = APIRouter(tags=["confirmation"])
log = get_logger()

# El token viaja en la URL: que no salga en el Referer, ni quede en cachés, ni se indexe.
_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    ),
}
_RESPONSES: dict[int | str, dict[str, str]] = {
    404: {"description": "Enlace no válido"},
    410: {"description": "El enlace venció o ya se usó"},
}


@router.get(
    "/confirmar/{token}",
    response_class=HTMLResponse,
    summary="Página de confirmación de una alerta (abrirla no confirma nada)",
    responses=_RESPONSES,
)
async def get_confirmation(token: str, conn: DbConnection, clock: ClockDep) -> HTMLResponse:
    view = await preview_confirmation(
        token, confirmations=SqlConfirmationRepository(conn), clock=clock
    )
    status_code, html = render_preview(view)
    return HTMLResponse(html, status_code=status_code, headers=_HEADERS)


@router.post(
    "/confirmar/{token}",
    response_class=HTMLResponse,
    summary="Confirmar una alerta: confirma su incidente y detiene el escalamiento",
    responses=_RESPONSES,
)
async def post_confirmation(token: str, conn: DbConnection, clock: ClockDep) -> HTMLResponse:
    view = await confirm_alert(
        token,
        confirmations=SqlConfirmationRepository(conn),
        incidents=SqlIncidentRepository(conn),
        clock=clock,
    )
    if view.alert is not None:  # nunca el token: basta con saber de qué alerta se trató
        log.info(
            "alert_confirmation",
            outcome=str(view.outcome),
            alert_id=str(view.alert.alert_id),
            incident_id=str(view.alert.incident_id),
        )
    status_code, html = render_result(view)
    return HTMLResponse(html, status_code=status_code, headers=_HEADERS)
