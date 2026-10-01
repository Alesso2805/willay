from typing import Any

import pytest

from vigia.territory.domain.zones import (
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
        pytest.param({"type": "Point", "coordinates": [-76.7, -11.9]}, "Polygon", id="point"),
        pytest.param({"type": "Polygon", "coordinates": []}, "anillo exterior", id="no-rings"),
        pytest.param({"type": "MultiPolygon", "coordinates": []}, "no tiene", id="no-polygons"),
        pytest.param(
            {"type": "Polygon", "coordinates": [SQUARE[:-1]]}, "no está cerrado", id="open-ring"
        ),
        pytest.param(
            {"type": "Polygon", "coordinates": [[SQUARE[0], SQUARE[1], SQUARE[0]]]},
            "al menos 3",
            id="two-vertices",
        ),
        pytest.param(
            {
                "type": "Polygon",
                # Tokyo with lat/lon swapped: latitude 139 is impossible (swapped Lima would pass).
                "coordinates": [[[35.6, 139.6], [35.7, 139.6], [35.7, 139.8], [35.6, 139.6]]],
            },
            "invertidas",
            id="swapped-lat-lon",
        ),
        pytest.param(
            {"type": "Polygon", "coordinates": [[["a", "b"], [1, 1], [1, 2], ["a", "b"]]]},
            "números",
            id="non-numeric",
        ),
        pytest.param(
            {"type": "Polygon", "coordinates": [[[1], [2], [3], [1]]]},
            "longitud, latitud",
            id="short-position",
        ),
    ],
)
def test_structurally_invalid_geometries_are_rejected_with_a_reason(
    geojson: dict[str, Any], reason: str
) -> None:
    with pytest.raises(InvalidGeometryError, match=reason):
        to_multipolygon(geojson)


def test_too_many_vertices_are_rejected() -> None:
    ring = [[-76.7 + i * 1e-6, -11.9] for i in range(MAX_VERTICES)]
    ring += [[-76.7, -12.0], ring[0]]
    with pytest.raises(InvalidGeometryError, match="máximo"):
        to_multipolygon({"type": "Polygon", "coordinates": [ring]})
