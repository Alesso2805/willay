"""Confirming an alert from its link, without login: the token is the credential.

GET only shows the page (email scanners open links on their own); only the button's POST
confirms. No CSRF protection needed: the POST cannot be built without the token, and
there is no session or cookie another site could ride on.
"""

from typing import Annotated

from fastapi import APIRouter, Header
from fastapi.responses import HTMLResponse
from structlog import get_logger

from willay.alerts.api.pages import page_language, render_preview, render_result
from willay.alerts.application.confirmation import confirm_alert, preview_confirmation
from willay.alerts.infrastructure.sql_confirmation import SqlConfirmationRepository
from willay.incidents.api.dependencies import IncidentRepositoryDep
from willay.shared.web import ClockDep, DbConnection

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
async def get_confirmation(
    token: str,
    conn: DbConnection,
    clock: ClockDep,
    accept_language: Annotated[str | None, Header()] = None,
) -> HTMLResponse:
    view = await preview_confirmation(
        token, confirmations=SqlConfirmationRepository(conn), clock=clock
    )
    language = page_language(view, accept_language)
    status_code, html = render_preview(view, language)
    return HTMLResponse(html, status_code, headers=_HEADERS | {"Content-Language": language})


@router.post(
    "/confirmar/{token}",
    response_class=HTMLResponse,
    summary="Acknowledge an alert: acknowledges its incident and stops the escalation",
    responses=_RESPONSES,
)
async def post_confirmation(
    token: str,
    conn: DbConnection,
    clock: ClockDep,
    incidents: IncidentRepositoryDep,
    accept_language: Annotated[str | None, Header()] = None,
) -> HTMLResponse:
    view = await confirm_alert(
        token,
        confirmations=SqlConfirmationRepository(conn),
        incidents=incidents,
        clock=clock,
    )
    if view.alert is not None:  # never log the token: the alert id is enough
        log.info(
            "alert_confirmation",
            outcome=str(view.outcome),
            alert_id=str(view.alert.alert_id),
            incident_id=str(view.alert.incident_id),
        )
    language = page_language(view, accept_language)
    status_code, html = render_result(view, language)
    return HTMLResponse(html, status_code, headers=_HEADERS | {"Content-Language": language})
