"""API de contactos: por ahora, el enlace para vincular su Telegram (VIG-21).

Solo admin (SPEC: gestionar contactos). El enlace se muestra una sola vez: la base guarda
solo el hash de su token, así que no se puede volver a leer; si se pierde, se genera otro
y el anterior deja de valer.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from vigia.alerts.application.policies import Actor
from vigia.alerts.application.telegram_link import (
    ContactNotFoundError,
    TelegramNotConfiguredError,
    create_telegram_link,
)
from vigia.alerts.infrastructure.sql_contact_links import SqlContactLinkRepository
from vigia.identity.api.dependencies import require
from vigia.identity.domain.permissions import Permission
from vigia.identity.domain.principal import Principal
from vigia.shared.audit import SqlAuditLog
from vigia.shared.web import ClockDep, DbConnection, SettingsDep

router = APIRouter(prefix="/v1/contacts", tags=["alerts"])

CanManage = Annotated[Principal, Depends(require(Permission.MANAGE_CONTACTS))]


class TelegramLinkOut(BaseModel):
    url: str
    expires_at: datetime


@router.post(
    "/{contact_id}/telegram-link",
    status_code=status.HTTP_201_CREATED,
    summary="Enlace de un solo uso para que el contacto vincule su Telegram (se muestra una vez)",
    responses={
        404: {"description": "El contacto no existe"},
        503: {"description": "El bot de Telegram no está configurado"},
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
            detail="El bot de Telegram no está configurado (VIGIA_TELEGRAM_BOT_USERNAME).",
        ) from exc
    response.headers["Cache-Control"] = "no-store"  # el enlace es un secreto de un solo uso
    return TelegramLinkOut(url=link.url, expires_at=link.expires_at)
