"""Zonas de riesgo: datos y validación estructural de su geometría.

La validación va en dos niveles:
- Estructura (aquí, Python puro): tipo, anillos cerrados, mínimo de puntos, rango de
  coordenadas y tope de vértices. Rechaza lo que ni siquiera es un polígono.
- Topología (PostGIS, ST_IsValid): autointersecciones, anillos que se tocan, etc. Es
  difícil de hacer bien a mano y PostGIS es la autoridad sobre lo que guarda.

Un polígono inválido se rechaza con su motivo; nunca se "arregla" en silencio: una zona
corregida automáticamente podría no cubrir lo que el operador dibujó.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

MAX_NAME_LENGTH = 120
# Un polígono dibujado a mano tiene decenas de vértices; importado de un SIG, algunos
# miles. El tope evita que un cliente mande megabytes de geometría en una petición.
MAX_VERTICES = 5000

Position = tuple[float, float]  # (longitud, latitud), en el orden de GeoJSON
Ring = list[Position]
PolygonCoords = list[Ring]  # anillo exterior y, opcionalmente, huecos
MultiPolygonCoords = list[PolygonCoords]


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class InvalidGeometryError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ZoneData:
    """Lo que el operador define de una zona (sin id ni fechas)."""

    name: str
    description: str | None
    risk_level: RiskLevel
    population_estimate: int | None
    geometry: MultiPolygonCoords
    is_active: bool = True


def to_multipolygon(geojson: Mapping[str, Any]) -> MultiPolygonCoords:
    """Acepta un Polygon (lo que dibuja Leaflet-Geoman) o un MultiPolygon GeoJSON y
    devuelve siempre coordenadas de MultiPolygon, el tipo de la columna."""
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
        raise InvalidGeometryError("la geometría debe ser un Polygon o un MultiPolygon GeoJSON")
    if not polygons:
        raise InvalidGeometryError("la geometría no tiene polígonos")

    result = [_polygon(polygon) for polygon in polygons]
    vertices = sum(len(ring) for polygon in result for ring in polygon)
    if vertices > MAX_VERTICES:
        raise InvalidGeometryError(f"la geometría tiene {vertices} vértices; máximo {MAX_VERTICES}")
    return result


def to_geojson(geometry: MultiPolygonCoords) -> dict[str, Any]:
    return {
        "type": "MultiPolygon",
        "coordinates": [[[list(position) for position in ring] for ring in p] for p in geometry],
    }


def _polygon(raw: object) -> PolygonCoords:
    if not isinstance(raw, list) or not raw:
        raise InvalidGeometryError("cada polígono necesita al menos un anillo exterior")
    return [_ring(ring) for ring in raw]


def _ring(raw: object) -> Ring:
    if not isinstance(raw, list):
        raise InvalidGeometryError("un anillo debe ser una lista de posiciones")
    ring = [_position(position) for position in raw]
    # GeoJSON exige anillos cerrados de al menos 4 posiciones: un triángulo es A-B-C-A.
    if len(ring) < 4:
        raise InvalidGeometryError(
            "un anillo necesita al menos 3 vértices distintos (4 posiciones)"
        )
    if ring[0] != ring[-1]:
        raise InvalidGeometryError(
            "el anillo no está cerrado: la última posición debe repetir la primera"
        )
    return ring


def _position(raw: object) -> Position:
    if not isinstance(raw, Sequence) or isinstance(raw, str) or len(raw) < 2:
        raise InvalidGeometryError("cada posición debe ser [longitud, latitud]")
    lon, lat = raw[0], raw[1]
    if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in (lon, lat)):
        raise InvalidGeometryError("las coordenadas deben ser números")
    # Detecta latitud y longitud invertidas solo cuando la latitud queda fuera de ±90 (p. ej.
    # en Asia). En Lima, [-11.9, -76.7] invertido sigue siendo válido (cae en la Antártida):
    # eso lo delata el mapa, no el rango.
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise InvalidGeometryError(
            f"coordenada fuera de rango: [{lon}, {lat}] (¿longitud y latitud invertidas?)"
        )
    return (float(lon), float(lat))
