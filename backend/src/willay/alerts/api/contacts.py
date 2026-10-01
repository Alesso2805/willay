"""Contacts API: for now, the link to connect a contact's Telegram (VIG-21).

Admin only (SPEC: manage contacts). The link is shown once: only its token hash is stored,
so it cannot be read again; if lost, a new one is generated and the old one stops working.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from willay.alerts.application.policies import Actor
from willay.alerts.application.telegram_link import (
    ContactNotFoundError,
    TelegramNotConfiguredError,
    create_telegram_link,
)
from willay.alerts.infrastructure.sql_contact_links import SqlContactLinkRepository
from willay.identity.api.dependencies import require
from willay.identity.domain.permissions import Permission
from willay.identity.domain.principal import Principal
from willay.shared.audit import SqlAuditLog
from willay.shared.web import ClockDep, DbConnection, SettingsDep

router = APIRouter(prefix="/v1/contacts", tags=["alerts"])

CanManage = Annotated[Principal, Depends(require(Permission.MANAGE_CONTACTS))]


class TelegramLinkOut(BaseModel):
    url: str
    expires_at: datetime


@router.post(
    "/{contact_id}/telegram-link",
    status_code=status.HTTP_201_CREATED,
    summary="Single-use link for the contact to link their Telegram (shown once)",
    responses={
        404: {"description": "The contact does not exist"},
        503: {"description": "The Telegram bot is not configured"},
    },
)
async def post_telegram_link(
    contact_id: UUID,
    principal: CanManage,
    conn: DbConnection,
    clock: ClockDep,
    settings: SettingsDep,
    response: Response,
) -> TelegramLinkOut:
    try:
        link = await create_telegram_link(
            Actor(principal.organization_id, principal.user_id),
            contact_id,
            contacts=SqlContactLinkRepository(conn),
            audit=SqlAuditLog(conn),
            clock=clock,
            bot_username=settings.telegram_bot_username,
        )
    except ContactNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Contacto no encontrado") from exc
    except TelegramNotConfiguredError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El bot de Telegram no está configurado (WILLAY_TELEGRAM_BOT_USERNAME).",
        ) from exc
    response.headers["Cache-Control"] = "no-store"  # the link is a single-use secret
    return TelegramLinkOut(url=link.url, expires_at=link.expires_at)
