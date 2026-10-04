"""Risk zones: data and structural validation of their geometry.

Two validation levels:
- Structure (here, pure Python): type, closed rings, minimum points, coordinate range and a
  vertex cap. Rejects what is not even a polygon.
- Topology (PostGIS, ST_IsValid): self-intersections, touching rings, etc. Hard to get right by
  hand, and PostGIS is the authority on what it stores.

An invalid polygon is rejected with its reason, never silently "fixed": an auto-corrected zone
might not cover what the operator drew.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from willay.shared.errors import ErrorCode, FieldError

MAX_NAME_LENGTH = 120
# A hand-drawn polygon has tens of vertices; one imported from a GIS, a few thousand. The cap
# stops a client from sending megabytes of geometry in one request.
MAX_VERTICES = 5000

Position = tuple[float, float]  # (longitude, latitude), GeoJSON order
Ring = list[Position]
PolygonCoords = list[Ring]  # exterior ring and, optionally, holes
MultiPolygonCoords = list[PolygonCoords]


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class InvalidGeometryError(FieldError):
    def __init__(self, code: ErrorCode, **params: object) -> None:
        super().__init__("geometry", code, **params)


@dataclass(frozen=True)
class ZoneData:
    """What the operator defines for a zone (no id or timestamps)."""

    name: str
    description: str | None
    risk_level: RiskLevel
    population_estimate: int | None
    geometry: MultiPolygonCoords
    is_active: bool = True


def to_multipolygon(geojson: Mapping[str, Any]) -> MultiPolygonCoords:
    """Accept a GeoJSON Polygon (what Leaflet-Geoman draws) or MultiPolygon and always
    return MultiPolygon coordinates, the column type."""
    kind = geojson.get("type")
    coordinates = geojson.get("coordinates")
    polygons: list[Any]
    if kind == "Polygon":
        polygons = [coordinates]
    elif kind == "MultiPolygon" and isinstance(coordinates, list):
        polygons = coordinates
    elif kind == "MultiPolygon":
        polygons = []
    else:
        raise InvalidGeometryError(ErrorCode.GEOMETRY_TYPE)
    if not polygons:
        raise InvalidGeometryError(ErrorCode.GEOMETRY_EMPTY)

    result = [_polygon(polygon) for polygon in polygons]
    vertices = sum(len(ring) for polygon in result for ring in polygon)
    if vertices > MAX_VERTICES:
        raise InvalidGeometryError(
            ErrorCode.GEOMETRY_TOO_MANY_VERTICES, vertices=vertices, max=MAX_VERTICES
        )
    return result


def to_geojson(geometry: MultiPolygonCoords) -> dict[str, Any]:
    return {
        "type": "MultiPolygon",
        "coordinates": [[[list(position) for position in ring] for ring in p] for p in geometry],
    }


def _polygon(raw: object) -> PolygonCoords:
    if not isinstance(raw, list) or not raw:
        raise InvalidGeometryError(ErrorCode.GEOMETRY_NO_RING)
    return [_ring(ring) for ring in raw]


def _ring(raw: object) -> Ring:
    if not isinstance(raw, list):
        raise InvalidGeometryError(ErrorCode.GEOMETRY_RING_TYPE)
    ring = [_position(position) for position in raw]
    # GeoJSON requires closed rings of at least 4 positions: a triangle is A-B-C-A.
    if len(ring) < 4:
        raise InvalidGeometryError(ErrorCode.GEOMETRY_RING_TOO_SHORT)
    if ring[0] != ring[-1]:
        raise InvalidGeometryError(ErrorCode.GEOMETRY_RING_OPEN)
    return ring


def _position(raw: object) -> Position:
    if not isinstance(raw, Sequence) or isinstance(raw, str) or len(raw) < 2:
        raise InvalidGeometryError(ErrorCode.GEOMETRY_POSITION)
    lon, lat = raw[0], raw[1]
    if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in (lon, lat)):
        raise InvalidGeometryError(ErrorCode.GEOMETRY_NOT_NUMBERS)
    # Catches swapped lat/lon only when latitude falls outside ±90 (e.g. in Asia). In Lima,
    # swapped [-11.9, -76.7] is still valid (lands in Antarctica): the map reveals that.
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise InvalidGeometryError(ErrorCode.GEOMETRY_OUT_OF_RANGE, lon=lon, lat=lat)
    return (float(lon), float(lat))
