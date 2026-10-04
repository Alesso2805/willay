from typing import Any

import pytest

from willay.shared.errors import ErrorCode
from willay.territory.domain.zones import (
    MAX_VERTICES,
    InvalidGeometryError,
    to_geojson,
    to_multipolygon,
)

SQUARE = [[-76.70, -11.90], [-76.60, -11.90], [-76.60, -12.00], [-76.70, -12.00], [-76.70, -11.90]]


def test_polygon_is_stored_as_multipolygon() -> None:
    result = to_multipolygon({"type": "Polygon", "coordinates": [SQUARE]})
    assert len(result) == 1
    assert result[0][0][0] == (-76.70, -11.90)
    assert to_geojson(result) == {"type": "MultiPolygon", "coordinates": [[SQUARE]]}


def test_multipolygon_with_a_hole_is_accepted() -> None:
    hole = [
        [-76.66, -11.94],
        [-76.64, -11.94],
        [-76.64, -11.96],
        [-76.66, -11.96],
        [-76.66, -11.94],
    ]
    result = to_multipolygon({"type": "MultiPolygon", "coordinates": [[SQUARE, hole]]})
    assert len(result[0]) == 2


@pytest.mark.parametrize(
    ("geojson", "reason"),
    [
        pytest.param(
            {"type": "Point", "coordinates": [-76.7, -11.9]}, ErrorCode.GEOMETRY_TYPE, id="point"
        ),
        pytest.param(
            {"type": "Polygon", "coordinates": []}, ErrorCode.GEOMETRY_NO_RING, id="no-rings"
        ),
        pytest.param(
            {"type": "MultiPolygon", "coordinates": []}, ErrorCode.GEOMETRY_EMPTY, id="no-polygons"
        ),
        pytest.param(
            {"type": "Polygon", "coordinates": [SQUARE[:-1]]},
            ErrorCode.GEOMETRY_RING_OPEN,
            id="open-ring",
        ),
        pytest.param(
            {"type": "Polygon", "coordinates": [[SQUARE[0], SQUARE[1], SQUARE[0]]]},
            ErrorCode.GEOMETRY_RING_TOO_SHORT,
            id="two-vertices",
        ),
        pytest.param(
            {
                "type": "Polygon",
                # Tokyo with lat/lon swapped: latitude 139 is impossible (swapped Lima would pass).
                "coordinates": [[[35.6, 139.6], [35.7, 139.6], [35.7, 139.8], [35.6, 139.6]]],
            },
            ErrorCode.GEOMETRY_OUT_OF_RANGE,
            id="swapped-lat-lon",
        ),
        pytest.param(
            {"type": "Polygon", "coordinates": [[["a", "b"], [1, 1], [1, 2], ["a", "b"]]]},
            ErrorCode.GEOMETRY_NOT_NUMBERS,
            id="non-numeric",
        ),
        pytest.param(
            {"type": "Polygon", "coordinates": [[[1], [2], [3], [1]]]},
            ErrorCode.GEOMETRY_POSITION,
            id="short-position",
        ),
    ],
)
def test_structurally_invalid_geometries_are_rejected_with_a_reason(
    geojson: dict[str, Any], reason: ErrorCode
) -> None:
    with pytest.raises(InvalidGeometryError) as caught:
        to_multipolygon(geojson)
    assert (caught.value.field, caught.value.code) == ("geometry", reason)


def test_too_many_vertices_are_rejected() -> None:
    ring = [[-76.7 + i * 1e-6, -11.9] for i in range(MAX_VERTICES)]
    ring += [[-76.7, -12.0], ring[0]]
    with pytest.raises(InvalidGeometryError, match=ErrorCode.GEOMETRY_TOO_MANY_VERTICES):
        to_multipolygon({"type": "Polygon", "coordinates": [ring]})
