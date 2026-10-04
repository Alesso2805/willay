"""Stations: data, unit per variable, code and zone assignment.

Product decisions (SPEC.md, scope, "Territorio - Estaciones" row):
- The unit is not chosen: it follows from the variable, so a threshold rule never compares
  metres with centimetres.
- The code identifies the station outside Willay (documents, field crews, simulator key file):
  fixed at creation and never changed. The name is editable.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from willay.shared.errors import ErrorCode, FieldError

MAX_NAME_LENGTH = 120
# Uppercase letters, digits and dashes, like RIM-CHA-01. Normalized to uppercase.
CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,31}$")
# The silence detector runs every 15 s: shorter intervals add nothing.
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


class InvalidStationError(FieldError):
    pass


@dataclass(frozen=True)
class Location:
    lon: float
    lat: float

    def __post_init__(self) -> None:
        if not (-180 <= self.lon <= 180 and -90 <= self.lat <= 90):
            raise InvalidStationError(
                "location", ErrorCode.STATION_LOCATION_RANGE, lon=self.lon, lat=self.lat
            )


@dataclass(frozen=True)
class ZoneAssignment:
    zone_id: UUID
    position: ZonePosition


@dataclass(frozen=True)
class StationData:
    """The editable part of a station (the code is separate: it never changes)."""

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
        raise InvalidStationError("code", ErrorCode.STATION_CODE_FORMAT)
    return code


def check_zones(zones: tuple[ZoneAssignment, ...]) -> None:
    """A station has one position per zone: upstream OR in the zone OR downstream."""
    if len(zones) > MAX_ZONES:
        raise InvalidStationError("zones", ErrorCode.STATION_TOO_MANY_ZONES, max=MAX_ZONES)
    ids = [zone.zone_id for zone in zones]
    if len(ids) != len(set(ids)):
        raise InvalidStationError("zones", ErrorCode.STATION_ZONE_REPEATED)
