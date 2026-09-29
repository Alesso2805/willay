from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from vigia.ingestion.api.dependencies import CurrentStation
from vigia.ingestion.application.ingest_batch import ingest_batch
from vigia.ingestion.domain.readings import MAX_BATCH_SIZE, FutureReadingsError, Reading
from vigia.ingestion.infrastructure.repositories import SqlReadingWriter
from vigia.shared.web import ClockDep, DbConnection

router = APIRouter(prefix="/v1", tags=["ingestion"])


class ReadingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # AwareDatetime: sin zona horaria no se puede saber cuándo se midió (422).
    measured_at: AwareDatetime
    # allow_inf_nan=False: un NaN o infinito es un sensor averiado, no una lectura.
    value: Annotated[float, Field(allow_inf_nan=False)]


class ReadingBatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    readings: Annotated[list[ReadingIn], Field(min_length=1, max_length=MAX_BATCH_SIZE)]


class ReadingBatchOut(BaseModel):
    received: int
    stored: int
    duplicates: int = Field(description="Ya existían por (estación, measured_at); se ignoran.")


@router.post(
    "/readings",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Lote de lecturas de la estación dueña de la API key",
    responses={
        401: {"description": "API key ausente o inválida"},
        403: {"description": "Estación inactiva"},
    },
)
async def post_readings(
    batch: ReadingBatchIn,
    station: CurrentStation,
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
        received=result.received, stored=result.stored, duplicates=result.duplicates
    )


def _utc(value: datetime) -> datetime:
    # Todo en UTC en la base (NFR de tiempo); la estación puede enviar cualquier offset.
    return value.astimezone(UTC)
