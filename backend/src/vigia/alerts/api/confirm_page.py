"""Confirming an alert from its link (VIG-23), without login: the token is the credential.

GET only shows the page (email scanners open links on their own); only the button's POST
confirms. No CSRF protection needed: the POST cannot be built without the token, and
there is no session or cookie another site could ride on.
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

# The token travels in the URL: keep it out of the Referer, caches and search indexes.
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
    404: {"description": "Invalid link"},
    410: {"description": "The link expired or was already used"},
}


@router.get(
    "/confirmar/{token}",
    response_class=HTMLResponse,
    summary="Confirmation page of an alert (opening it acknowledges nothing)",
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
    summary="Acknowledge an alert: acknowledges its incident and stops the escalation",
    responses=_RESPONSES,
)
async def post_confirmation(token: str, conn: DbConnection, clock: ClockDep) -> HTMLResponse:
    view = await confirm_alert(
        token,
        confirmations=SqlConfirmationRepository(conn),
        incidents=SqlIncidentRepository(conn),
        clock=clock,
    )
    if view.alert is not None:  # never log the token: the alert id is enough
        log.info(
            "alert_confirmation",
            outcome=str(view.outcome),
            alert_id=str(view.alert.alert_id),
            incident_id=str(view.alert.incident_id),
        )
    status_code, html = render_result(view)
    return HTMLResponse(html, status_code=status_code, headers=_HEADERS)
