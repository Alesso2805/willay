"""API REST de zonas de riesgo (VIG-12). La geometría viaja como GeoJSON (lon, lat)."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from vigia.identity.api.dependencies import require
from vigia.identity.domain.permissions import Permission
from vigia.identity.domain.principal import Principal
from vigia.shared.audit import SqlAuditLog
from vigia.shared.web import ClockDep, DbConnection
from vigia.territory.application.zones import (
    Actor,
    Zone,
    ZoneNotFoundError,
    create_zone,
    deactivate_zone,
    update_zone,
)
from vigia.territory.domain.zones import (
    MAX_NAME_LENGTH,
    InvalidGeometryError,
    RiskLevel,
    ZoneData,
    to_geojson,
    to_multipolygon,
)
from vigia.territory.infrastructure.zones_repository import SqlZoneRepository

router = APIRouter(prefix="/v1/zones", tags=["territory"])

CanView = Annotated[Principal, Depends(require(Permission.VIEW))]
CanManage = Annotated[Principal, Depends(require(Permission.MANAGE_TERRITORY))]

_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="Zona no encontrada")


class GeoJsonGeometry(BaseModel):
    """Polygon (lo que dibuja el mapa) o MultiPolygon. Coordenadas [longitud, latitud]."""

    type: Literal["Polygon", "MultiPolygon"]
    coordinates: list[Any]


class ZoneIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Annotated[str, Field(min_length=1, max_length=MAX_NAME_LENGTH)]
    description: Annotated[str | None, Field(max_length=2000)] = None
    risk_level: RiskLevel
    population_estimate: Annotated[int | None, Field(ge=0)] = None
    geometry: GeoJsonGeometry
    is_active: bool = True


class ZoneOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    risk_level: RiskLevel
    population_estimate: int | None
    is_active: bool
    geometry: dict[str, Any] = Field(description="MultiPolygon GeoJSON")
    created_at: datetime
    updated_at: datetime


@router.get("", summary="Zonas de la organización")
async def list_zones(
    principal: CanView,
    conn: DbConnection,
    include_inactive: Annotated[bool, Query(description="incluir las desactivadas")] = False,
) -> list[ZoneOut]:
    zones = await SqlZoneRepository(conn).list(
        principal.organization_id, include_inactive=include_inactive
    )
    return [_out(zone) for zone in zones]


@router.get("/{zone_id}", summary="Una zona", responses={404: {"description": "No existe"}})
async def get_zone(zone_id: UUID, principal: CanView, conn: DbConnection) -> ZoneOut:
    zone = await SqlZoneRepository(conn).get(principal.organization_id, zone_id)
    if zone is None:
        raise _NOT_FOUND
    return _out(zone)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Crear una zona",
    responses={422: {"description": "Datos o geometría inválidos (el motivo va en el detalle)"}},
)
async def post_zone(
    body: ZoneIn, principal: CanManage, conn: DbConnection, clock: ClockDep, response: Response
) -> ZoneOut:
    data = _data(body)
    try:
        zone = await create_zone(
            _actor(principal),
            data,
            zones=SqlZoneRepository(conn),
            audit=SqlAuditLog(conn),
            clock=clock,
        )
    except InvalidGeometryError as exc:
        raise _invalid_geometry(exc) from exc
    response.headers["Location"] = f"/v1/zones/{zone.id}"
    return _out(zone)


@router.put(
    "/{zone_id}",
    summary="Reemplazar una zona (atributos y geometría; también reactiva)",
    responses={
        404: {"description": "No existe"},
        422: {"description": "Datos o geometría inválidos"},
    },
)
async def put_zone(
    zone_id: UUID, body: ZoneIn, principal: CanManage, conn: DbConnection, clock: ClockDep
) -> ZoneOut:
    data = _data(body)
    try:
        zone = await update_zone(
            _actor(principal),
            zone_id,
            data,
            zones=SqlZoneRepository(conn),
            audit=SqlAuditLog(conn),
            clock=clock,
        )
    except ZoneNotFoundError as exc:
        raise _NOT_FOUND from exc
    except InvalidGeometryError as exc:
        raise _invalid_geometry(exc) from exc
    return _out(zone)


@router.delete(
    "/{zone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Desactivar una zona (no se borra: la historia de sus incidentes se conserva)",
    responses={404: {"description": "No existe"}},
)
async def delete_zone(
    zone_id: UUID, principal: CanManage, conn: DbConnection, clock: ClockDep
) -> None:
    try:
        await deactivate_zone(
            _actor(principal),
            zone_id,
            zones=SqlZoneRepository(conn),
            audit=SqlAuditLog(conn),
            clock=clock,
        )
    except ZoneNotFoundError as exc:
        raise _NOT_FOUND from exc


def _actor(principal: Principal) -> Actor:
    return Actor(principal.organization_id, principal.user_id)


def _data(body: ZoneIn) -> ZoneData:
    try:
        geometry = to_multipolygon(body.geometry.model_dump())
    except InvalidGeometryError as exc:
        raise _invalid_geometry(exc) from exc
    return ZoneData(
        name=body.name,
        description=body.description or None,
        risk_level=body.risk_level,
        population_estimate=body.population_estimate,
        geometry=geometry,
        is_active=body.is_active,
    )


def _invalid_geometry(exc: InvalidGeometryError) -> HTTPException:
    # Mismo formato que los 422 de validación de FastAPI, para que el panel los trate igual.
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[{"loc": ["body", "geometry"], "msg": exc.reason, "type": "invalid_geometry"}],
    )


def _out(zone: Zone) -> ZoneOut:
    return ZoneOut(
        id=zone.id,
        name=zone.data.name,
        description=zone.data.description,
        risk_level=zone.data.risk_level,
        population_estimate=zone.data.population_estimate,
        is_active=zone.data.is_active,
        geometry=to_geojson(zone.data.geometry),
        created_at=zone.created_at,
        updated_at=zone.updated_at,
    )
