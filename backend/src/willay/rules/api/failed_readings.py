"""Failed readings API (VIG-39): what the evaluator gave up on, and sending it back.

Operator and admin only (SPEC: "See and reprocess readings whose evaluation failed"). The
dashboard header asks for the count whenever the live channel says it changed.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from willay.identity.api.dependencies import require
from willay.identity.domain.permissions import Permission
from willay.identity.domain.principal import Principal
from willay.rules.application.failed_readings import (
    MAX_LISTED,
    MAX_REPROCESSED,
    Actor,
    FailedReading,
    reprocess,
)
from willay.rules.infrastructure.sql_failed_readings import SqlFailedReadingRepository
from willay.shared.audit import SqlAuditLog
from willay.shared.web import ClockDep, DbConnection

router = APIRouter(prefix="/v1/failed-readings", tags=["rules"])

CanReprocess = Annotated[Principal, Depends(require(Permission.REPROCESS_READINGS))]


class FailedReadingOut(BaseModel):
    id: int
    station_id: UUID
    station_code: str
    station_name: str
    measured_at: datetime
    value: float | None
    unit: str
    attempts: int
    failed_at: datetime
    last_error: str | None


class FailedCountOut(BaseModel):
    count: int


class ReprocessIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[int] = Field(min_length=1, max_length=MAX_REPROCESSED)


class ReprocessOut(BaseModel):
    reprocessed: int  # ids already reprocessed, or another organization's, are not counted


@router.get("", summary=f"Readings whose evaluation failed, most recent first (up to {MAX_LISTED})")
async def list_failed(principal: CanReprocess, conn: DbConnection) -> list[FailedReadingOut]:
    failed = await SqlFailedReadingRepository(conn).all_of(
        principal.organization_id, limit=MAX_LISTED
    )
    return [_out(reading) for reading in failed]


@router.get("/count", summary="How many readings failed evaluation")
async def count_failed(principal: CanReprocess, conn: DbConnection) -> FailedCountOut:
    return FailedCountOut(
        count=await SqlFailedReadingRepository(conn).count(principal.organization_id)
    )


@router.post("/reprocess", summary="Send failed readings back to the evaluation queue")
async def post_reprocess(
    body: ReprocessIn, principal: CanReprocess, conn: DbConnection, clock: ClockDep
) -> ReprocessOut:
    requeued = await reprocess(
        Actor(principal.organization_id, principal.user_id),
        frozenset(body.ids),
        readings=SqlFailedReadingRepository(conn),
        audit=SqlAuditLog(conn),
        clock=clock,
    )
    return ReprocessOut(reprocessed=len(requeued))


def _out(reading: FailedReading) -> FailedReadingOut:
    return FailedReadingOut(
        id=reading.id,
        station_id=reading.station_id,
        station_code=reading.station_code,
        station_name=reading.station_name,
        measured_at=reading.measured_at,
        value=reading.value,
        unit=reading.unit,
        attempts=reading.attempts,
        failed_at=reading.failed_at,
        last_error=reading.last_error,
    )
