"""Estaciones: datos, unidad por variable, código y asociación a zonas.

Decisiones de producto (SPEC.md, Alcance, fila "Territorio - Estaciones"):
- La unidad no se elige: sale de la variable, para que una regla de umbral nunca
  compare metros con centímetros.
- El código identifica la estación fuera de Vigía (documentos, equipo en campo, archivo
  de claves del simulador): se fija al crearla y no cambia. El nombre sí es editable.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

MAX_NAME_LENGTH = 120
# Mayúsculas, dígitos y guiones, como RIM-CHA-01. Se normaliza a mayúsculas.
CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,31}$")
# El detector de silencio revisa cada 15 s: intervalos menores no aportan nada.
MIN_INTERVAL_S = 5
MAX_INTERVAL_S = 86_400
MIN_SILENCE_MULTIPLIER = 1
MAX_SILENCE_MULTIPLIER = 20
MAX_ZONES = 50


class Variable(StrEnum):
    WATER_LEVEL = "water_level"
    DISCHARGE = "discharge"
    RAINFALL = "rainfall"


UNITS: dict[Variable, str] = {
    Variable.DISCHARGE: "m3/s",
    Variable.WATER_LEVEL: "m",
    Variable.RAINFALL: "mm",
}


class Source(StrEnum):
    SENSOR = "sensor"
    SIMULATOR = "simulator"


class StationStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class ZonePosition(StrEnum):
    UPSTREAM = "upstream"
    IN_ZONE = "in_zone"
    DOWNSTREAM = "downstream"


class InvalidStationError(Exception):
    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"{field}: {reason}")
        self.field = field
        self.reason = reason


@dataclass(frozen=True)
class Location:
    lon: float
    lat: float

    def __post_init__(self) -> None:
        if not (-180 <= self.lon <= 180 and -90 <= self.lat <= 90):
            raise InvalidStationError(
                "location", f"coordenada fuera de rango: [{self.lon}, {self.lat}]"
            )


@dataclass(frozen=True)
class ZoneAssignment:
    zone_id: UUID
    position: ZonePosition


@dataclass(frozen=True)
class StationData:
    """Lo editable de una estación (el código va aparte: no cambia)."""

    name: str
    variable: Variable
    location: Location
    source: Source
    expected_interval_s: int
    silence_multiplier: int
    status: StationStatus
    zones: tuple[ZoneAssignment, ...]

    @property
    def unit(self) -> str:
        return UNITS[self.variable]


def normalize_code(raw: str) -> str:
    code = raw.strip().upper()
    if not CODE_PATTERN.fullmatch(code):
        raise InvalidStationError(
            "code", "de 2 a 32 caracteres: letras, dígitos y guiones (p. ej. RIM-CHA-01)"
        )
    return code


def check_zones(zones: tuple[ZoneAssignment, ...]) -> None:
    """Una estación está en una zona con una sola posición: aguas arriba O dentro O abajo."""
    if len(zones) > MAX_ZONES:
        raise InvalidStationError("zones", f"máximo {MAX_ZONES} zonas por estación")
    ids = [zone.zone_id for zone in zones]
    if len(ids) != len(set(ids)):
        raise InvalidStationError("zones", "una zona aparece más de una vez")
