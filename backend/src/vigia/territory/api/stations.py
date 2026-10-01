"""Station REST API (VIG-13). Location travels as a GeoJSON Point [lon, lat]."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from vigia.identity.api.dependencies import require
from vigia.identity.domain.permissions import Permission
from vigia.identity.domain.principal import Principal
from vigia.ingestion.api.dependencies import get_api_key_hasher
from vigia.ingestion.infrastructure.api_keys import ApiKeyHasher, Argon2ApiKeyIssuer
from vigia.shared.audit import SqlAuditLog
from vigia.shared.web import ClockDep, DbConnection
from vigia.territory.application.stations import (
    DuplicateStationCodeError,
    IssuedStation,
    Station,
    StationNotFoundError,
    create_station,
    deactivate_station,
    rotate_api_key,
    update_station,
)
from vigia.territory.application.zones import Actor
from vigia.territory.domain.stations import (
    MAX_INTERVAL_S,
    MAX_NAME_LENGTH,
    MAX_SILENCE_MULTIPLIER,
    MAX_ZONES,
    MIN_INTERVAL_S,
    MIN_SILENCE_MULTIPLIER,
    InvalidStationError,
    Location,
    Source,
    StationData,
    StationStatus,
    Variable,
    ZoneAssignment,
    ZonePosition,
    normalize_code,
)
from vigia.territory.infrastructure.stations_repository import SqlStationRepository

router = APIRouter(prefix="/v1/stations", tags=["territory"])

CanView = Annotated[Principal, Depends(require(Permission.VIEW))]
CanManage = Annotated[Principal, Depends(require(Permission.MANAGE_TERRITORY))]
Hasher = Annotated[ApiKeyHasher, Depends(get_api_key_hasher)]

_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="Estación no encontrada")
# A response carrying a plaintext key must never be cached.
_NO_STORE = {"Cache-Control": "no-store"}


class GeoJsonPoint(BaseModel):
    type: Literal["Point"]
    coordinates: Annotated[list[float], Field(min_length=2, max_length=2)]


class ZoneAssignmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zone_id: UUID
    position: ZonePosition


class StationBodyIn(BaseModel):
    """The editable fields. The code is not here: it is set on creation and never changes."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Annotated[str, Field(min_length=1, max_length=MAX_NAME_LENGTH)]
    variable: Variable
    location: GeoJsonPoint
    source: Source = Source.SENSOR
    expected_interval_s: Annotated[int, Field(ge=MIN_INTERVAL_S, le=MAX_INTERVAL_S)]
    silence_multiplier: Annotated[
        int, Field(ge=MIN_SILENCE_MULTIPLIER, le=MAX_SILENCE_MULTIPLIER)
    ] = 3
    status: StationStatus = StationStatus.ACTIVE
    zones: Annotated[list[ZoneAssignmentIn], Field(max_length=MAX_ZONES)] = []


class StationCreateIn(StationBodyIn):
    code: Annotated[str, Field(min_length=2, max_length=32, examples=["RIM-CHA-01"])]


class HeartbeatOut(BaseModel):
    last_seen_at: datetime
    last_measured_at: datetime
    last_value: float | None


class StationOut(BaseModel):
    id: UUID
    code: str
    name: str
    variable: Variable
    unit: str = Field(description="Fixed per variable: discharge m3/s, water_level m, rainfall mm")
    location: dict[str, Any] = Field(description="GeoJSON Point [lon, lat]")
    source: Source
    expected_interval_s: int
    silence_multiplier: int
    status: StationStatus
    zones: list[ZoneAssignmentIn]
    has_zone: bool = Field(description="Without a zone, the station raises no alerts")
    heartbeat: HeartbeatOut | None
    api_key_rotated_at: datetime
    created_at: datetime


class IssuedKeyOut(BaseModel):
    station: StationOut
    api_key: str = Field(description="Shown only once; Willay only stores its hash")


@router.get("", summary="The organization's stations")
async def list_stations(
    principal: CanView,
    conn: DbConnection,
    include_inactive: Annotated[bool, Query(description="include deactivated ones")] = False,
) -> list[StationOut]:
    stations = await SqlStationRepository(conn).list(
        principal.organization_id, include_inactive=include_inactive
    )
    return [_out(station) for station in stations]


@router.get("/{station_id}", summary="A station", responses={404: {"description": "Not found"}})
async def get_station(station_id: UUID, principal: CanView, conn: DbConnection) -> StationOut:
    station = await SqlStationRepository(conn).get(principal.organization_id, station_id)
    if station is None:
        raise _NOT_FOUND
    return _out(station)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a station (returns its API key only once)",
    responses={409: {"description": "Duplicate code"}, 422: {"description": "Invalid data"}},
)
async def post_station(
    body: StationCreateIn,
    principal: CanManage,
    conn: DbConnection,
    clock: ClockDep,
    hasher: Hasher,
    response: Response,
) -> IssuedKeyOut:
    try:
        issued = await create_station(
            _actor(principal),
            normalize_code(body.code),
            _data(body),
            stations=SqlStationRepository(conn),
            issuer=Argon2ApiKeyIssuer(hasher),
            audit=SqlAuditLog(conn),
            clock=clock,
        )
    except InvalidStationError as exc:
        raise _invalid(exc) from exc
    except DuplicateStationCodeError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"Ya existe una estación con el código {exc}"
        ) from exc
    response.headers.update({"Location": f"/v1/stations/{issued.station.id}", **_NO_STORE})
    return _issued(issued)


@router.put(
    "/{station_id}",
    summary="Replace a station (the code does not change; also reactivates it)",
    responses={404: {"description": "Not found"}, 422: {"description": "Invalid data"}},
)
async def put_station(
    station_id: UUID, body: StationBodyIn, principal: CanManage, conn: DbConnection, clock: ClockDep
) -> StationOut:
    try:
        station = await update_station(
            _actor(principal),
            station_id,
            _data(body),
            stations=SqlStationRepository(conn),
            audit=SqlAuditLog(conn),
            clock=clock,
        )
    except StationNotFoundError as exc:
        raise _NOT_FOUND from exc
    except InvalidStationError as exc:
        raise _invalid(exc) from exc
    return _out(station)


@router.delete(
    "/{station_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a station (its batches get 403; its history is kept)",
    responses={404: {"description": "Not found"}},
)
async def delete_station(
    station_id: UUID, principal: CanManage, conn: DbConnection, clock: ClockDep
) -> None:
    try:
        await deactivate_station(
            _actor(principal),
            station_id,
            stations=SqlStationRepository(conn),
            audit=SqlAuditLog(conn),
            clock=clock,
        )
    except StationNotFoundError as exc:
        raise _NOT_FOUND from exc


@router.post(
    "/{station_id}/api-key",
    summary="Rotate the API key: the previous one stops working immediately",
    responses={404: {"description": "Not found"}},
)
async def post_api_key(
    station_id: UUID,
    principal: CanManage,
    conn: DbConnection,
    clock: ClockDep,
    hasher: Hasher,
    response: Response,
) -> IssuedKeyOut:
    try:
        issued = await rotate_api_key(
            _actor(principal),
            station_id,
            stations=SqlStationRepository(conn),
            issuer=Argon2ApiKeyIssuer(hasher),
            audit=SqlAuditLog(conn),
            clock=clock,
        )
    except StationNotFoundError as exc:
        raise _NOT_FOUND from exc
    response.headers.update(_NO_STORE)
    return _issued(issued)


def _actor(principal: Principal) -> Actor:
    return Actor(principal.organization_id, principal.user_id)


def _data(body: StationBodyIn) -> StationData:
    lon, lat = body.location.coordinates
    return StationData(
        name=body.name,
        variable=body.variable,
        location=_location(lon, lat),
        source=body.source,
        expected_interval_s=body.expected_interval_s,
        silence_multiplier=body.silence_multiplier,
        status=body.status,
        zones=tuple(ZoneAssignment(z.zone_id, z.position) for z in body.zones),
    )


def _location(lon: float, lat: float) -> Location:
    try:
        return Location(lon, lat)
    except InvalidStationError as exc:
        raise _invalid(exc) from exc


def _invalid(exc: InvalidStationError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[{"loc": ["body", exc.field], "msg": exc.reason, "type": "invalid_station"}],
    )


def _issued(issued: IssuedStation) -> IssuedKeyOut:
    return IssuedKeyOut(station=_out(issued.station), api_key=issued.api_key)


def _out(station: Station) -> StationOut:
    data = station.data
    heartbeat = station.heartbeat
    return StationOut(
        id=station.id,
        code=station.code,
        name=data.name,
        variable=data.variable,
        unit=data.unit,
        location={"type": "Point", "coordinates": [data.location.lon, data.location.lat]},
        source=data.source,
        expected_interval_s=data.expected_interval_s,
        silence_multiplier=data.silence_multiplier,
        status=data.status,
        zones=[ZoneAssignmentIn(zone_id=z.zone_id, position=z.position) for z in data.zones],
        has_zone=bool(data.zones),
        heartbeat=HeartbeatOut(
            last_seen_at=heartbeat.last_seen_at,
            last_measured_at=heartbeat.last_measured_at,
            last_value=heartbeat.last_value,
        )
        if heartbeat
        else None,
        api_key_rotated_at=station.api_key_rotated_at,
        created_at=station.created_at,
    )
