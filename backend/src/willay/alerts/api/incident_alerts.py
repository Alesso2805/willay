"""`GET /v1/incidents/{id}/alerts`: who was alerted, through which channel, and what happened.
Anyone who can see incidents can read it; the email only reaches users who may see
contact details, and a Telegram chat never leaves the API (alerts/domain/recipients.py).
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from willay.alerts.domain.alerts import AlertStatus, Channel
from willay.alerts.domain.recipients import shown_email
from willay.alerts.infrastructure.sql_incident_alerts import SqlIncidentAlerts
from willay.identity.api.dependencies import require
from willay.identity.domain.permissions import Permission, can
from willay.identity.domain.principal import Principal
from willay.shared.errors import ErrorCode
from willay.shared.web import ApiError, DbConnection

router = APIRouter(prefix="/v1/incidents", tags=["alerts"])

CanView = Annotated[Principal, Depends(require(Permission.VIEW))]


class IncidentAlertOut(BaseModel):
    id: UUID
    level_order: int
    contact_id: UUID
    contact_name: str
    channel: Channel
    status: AlertStatus
    attempts: int
    sent_at: datetime | None
    acknowledged_at: datetime | None
    skipped_reason_code: str | None = Field(
        description="Why it was not sent, for skipped alerts: no_email, no_telegram,"
        " incident_acknowledged or incident_resolved; the dashboard says it in words"
    )
    skipped_reason: str | None = Field(
        description="The reason as Spanish text, only for alerts skipped before VIG-40"
    )
    email: str | None = Field(
        description="Only for email alerts and only for users who may see contact details "
        "(operator, admin); a Telegram chat is never returned"
    )


@router.get(
    "/{incident_id}/alerts",
    summary="An incident's alerts, by level and recipient",
    responses={404: {"description": "Not found"}},
)
async def incident_alerts(
    incident_id: UUID, principal: CanView, conn: DbConnection
) -> list[IncidentAlertOut]:
    alerts = await SqlIncidentAlerts(conn).for_incident(principal.organization_id, incident_id)
    if alerts is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.INCIDENT_NOT_FOUND)
    may_see_details = can(principal, Permission.VIEW_CONTACT_DETAILS)
    return [
        IncidentAlertOut(
            id=a.id,
            level_order=a.level_order,
            contact_id=a.contact_id,
            contact_name=a.contact_name,
            channel=a.channel,
            status=a.status,
            attempts=a.attempts,
            sent_at=a.sent_at,
            acknowledged_at=a.acknowledged_at,
            skipped_reason_code=a.skipped_reason_code,
            skipped_reason=a.skipped_reason,
            email=shown_email(a.channel, a.destination, may_see_details),
        )
        for a in alerts
    ]
