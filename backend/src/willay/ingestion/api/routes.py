from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from willay.ingestion.api.dependencies import IngestingStation
from willay.ingestion.application.ingest_batch import ingest_batch
from willay.ingestion.domain.readings import MAX_BATCH_SIZE, FutureReadingsError, Reading
from willay.ingestion.infrastructure.repositories import SqlReadingWriter
from willay.shared.errors import ErrorCode
from willay.shared.web import ApiError, ClockDep, DbConnection, FieldProblem

router = APIRouter(prefix="/v1", tags=["ingestion"])
log = structlog.get_logger()


class ReadingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # AwareDatetime: without a timezone the measurement instant is unknown (422).
    measured_at: AwareDatetime
    # allow_inf_nan=False: NaN or infinity is a broken sensor, not a reading.
    value: Annotated[float, Field(allow_inf_nan=False)]


class ReadingBatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    readings: Annotated[list[ReadingIn], Field(min_length=1, max_length=MAX_BATCH_SIZE)]


class ReadingBatchOut(BaseModel):
    received: int
    stored: int
    duplicates: int = Field(description="Already stored for (station, measured_at); ignored.")
    late: int = Field(
        description="Of those stored, how many arrived more than 1 h late: they stay in the "
        "history but are not evaluated. Many late readings usually point to a faulty clock "
        "or link at the station."
    )
    correlation_id: UUID = Field(
        description="Appears in the logs of the evaluation, the incident and its alerts"
    )


@router.post(
    "/readings",
    status_code=status.HTTP_202_ACCEPTED,
    summary="A batch of readings from the station that owns the API key",
    responses={
        401: {"description": "Missing or invalid API key"},
        403: {"description": "Inactive station"},
        429: {
            "description": "More than 60 batches a minute from the station, or more than 30 "
            "requests with a wrong API key a minute from the same address; see the Retry-After "
            "header"
        },
    },
)
async def post_readings(
    batch: ReadingBatchIn,
    station: IngestingStation,  # before conn: the write connection is acquired last
    conn: DbConnection,
    clock: ClockDep,
) -> ReadingBatchOut:
    readings = [Reading(_utc(r.measured_at), r.value) for r in batch.readings]
    try:
        result = await ingest_batch(station, readings, clock, SqlReadingWriter(conn))
    except FutureReadingsError as exc:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.READING_IN_FUTURE,
            fields=[
                FieldProblem(
                    ["body", "readings", i, "measured_at"],
                    ErrorCode.READING_IN_FUTURE,
                    type="future_timestamp",
                )
                for i in exc.indices
            ],
        ) from exc
    log.info(
        "readings_ingested",
        correlation_id=str(result.correlation_id),
        station_id=str(station.station_id),
        received=result.received,
        stored=result.counts.stored,
        enqueued=result.counts.enqueued,
        late=result.counts.late,
    )
    return ReadingBatchOut(
        received=result.received,
        stored=result.counts.stored,
        duplicates=result.duplicates,
        late=result.counts.late,
        correlation_id=result.correlation_id,
    )


def _utc(value: datetime) -> datetime:
    # Everything is UTC in the database (time NFR); stations may send any offset.
    return value.astimezone(UTC)
