from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from willay.ingestion.api.dependencies import IngestingStation
from willay.ingestion.application.ingest_batch import ingest_batch
from willay.ingestion.domain.readings import MAX_BATCH_SIZE, FutureReadingsError, Reading
from willay.ingestion.infrastructure.repositories import SqlReadingWriter
from willay.shared.web import ClockDep, DbConnection

router = APIRouter(prefix="/v1", tags=["ingestion"])


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


@router.post(
    "/readings",
    status_code=status.HTTP_202_ACCEPTED,
    summary="A batch of readings from the station that owns the API key",
    responses={
        401: {"description": "Missing or invalid API key"},
        403: {"description": "Inactive station"},
        429: {"description": "More than 60 batches per minute; see the Retry-After header"},
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
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[
                {
                    "loc": ["body", "readings", i, "measured_at"],
                    "msg": "measured_at está en el futuro (reloj de la estación desfasado)",
                    "type": "future_timestamp",
                }
                for i in exc.indices
            ],
        ) from exc
    return ReadingBatchOut(
        received=result.received,
        stored=result.counts.stored,
        duplicates=result.duplicates,
        late=result.counts.late,
    )


def _utc(value: datetime) -> datetime:
    # Everything is UTC in the database (time NFR); stations may send any offset.
    return value.astimezone(UTC)
