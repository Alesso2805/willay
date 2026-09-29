from uuid import uuid4

import pytest

from vigia.territory.domain.stations import (
    InvalidStationError,
    Location,
    Source,
    StationData,
    StationStatus,
    Variable,
    ZoneAssignment,
    ZonePosition,
    check_zones,
    normalize_code,
)


@pytest.mark.parametrize(
    ("variable", "unit"),
    [(Variable.DISCHARGE, "m3/s"), (Variable.WATER_LEVEL, "m"), (Variable.RAINFALL, "mm")],
)
def test_unit_derives_from_the_variable(variable: Variable, unit: str) -> None:
    data = StationData(
        "X", variable, Location(-76.7, -11.9), Source.SENSOR, 10, 3, StationStatus.ACTIVE, ()
    )
    assert data.unit == unit


def test_code_is_normalized_to_uppercase() -> None:
    assert normalize_code("  rim-cha-01 ") == "RIM-CHA-01"


@pytest.mark.parametrize("raw", ["", "A", "-RIM", "RIM CHA", "RIM_CHA", "Ñ-01", "X" * 33])
def test_invalid_codes_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidStationError) as exc:
        normalize_code(raw)
    assert exc.value.field == "code"


@pytest.mark.parametrize(("lon", "lat"), [(-181, 0), (0, 91), (200, -11.9)])
def test_location_out_of_range_is_rejected(lon: float, lat: float) -> None:
    with pytest.raises(InvalidStationError, match="fuera de rango"):
        Location(lon, lat)


def test_a_zone_can_appear_only_once() -> None:
    zone = uuid4()
    check_zones(
        (ZoneAssignment(zone, ZonePosition.UPSTREAM), ZoneAssignment(uuid4(), ZonePosition.IN_ZONE))
    )
    with pytest.raises(InvalidStationError, match="más de una vez"):
        check_zones(
            (
                ZoneAssignment(zone, ZonePosition.UPSTREAM),
                ZoneAssignment(zone, ZonePosition.IN_ZONE),
            )
        )
