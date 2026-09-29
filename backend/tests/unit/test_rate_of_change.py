from datetime import timedelta
from typing import Any

import pytest

from vigia.rules.domain.errors import InvalidRuleParamsError
from vigia.rules.domain.rate_of_change import (
    Change,
    Direction,
    RateOfChangeParams,
    detect_change,
    parse_rate_of_change,
)

DOWN_40 = RateOfChangeParams(Direction.DOWN, 40.0, 10)
UP_40 = RateOfChangeParams(Direction.UP, 40.0, 10)


def test_seed_params_are_parsed() -> None:
    raw = {"direction": "down", "delta": 40.0, "window_minutes": 10}
    assert parse_rate_of_change(raw) == DOWN_40
    assert DOWN_40.window == timedelta(minutes=10)
    assert parse_rate_of_change({"direction": "up", "delta": 1, "window_minutes": 60}).delta == 1.0


@pytest.mark.parametrize(
    "raw",
    [
        {"delta": 40.0, "window_minutes": 10},
        {"direction": "sideways", "delta": 40.0, "window_minutes": 10},
        {"direction": "down", "delta": "mucho", "window_minutes": 10},
        {"direction": "down", "delta": True, "window_minutes": 10},
        {"direction": "down", "delta": 0, "window_minutes": 10},
        {"direction": "down", "delta": -5.0, "window_minutes": 10},
        {"direction": "down", "delta": 40.0, "window_minutes": 0},
        {"direction": "down", "delta": 40.0, "window_minutes": 61},
        {"direction": "down", "delta": 40.0, "window_minutes": 7.5},
        {"direction": "down", "delta": 40.0, "window_minutes": True},
    ],
)
def test_invalid_params_are_rejected(raw: dict[str, Any]) -> None:
    with pytest.raises(InvalidRuleParamsError):
        parse_rate_of_change(raw)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([85.0, 34.0], Change(0, 1, 51.0)),  # caída brusca
        ([85.0, 45.0], None),  # exactamente delta: "mayor a", no dispara
        ([85.0, 44.5], Change(0, 1, 40.5)),
        ([85.0, 34.0, 60.0], Change(0, 1, 51.0)),  # se recupera en parte: igual dispara
        ([80.0, 90.0, 60.0, 34.0], Change(1, 3, 56.0)),  # del pico, no de la primera
        ([34.0, 85.0], None),  # el valle antes del pico es una subida
        ([85.0, 60.0, 90.0, 55.0], None),  # dos caídas de 25 y 35: ninguna supera 40
        ([85.0], None),
        ([], None),
    ],
)
def test_a_drop_is_measured_from_the_peak_to_a_later_valley(
    values: list[float], expected: Change | None
) -> None:
    assert detect_change(DOWN_40, values) == expected


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([2.0, 45.0], Change(0, 1, 43.0)),
        ([45.0, 2.0], None),  # una caída no dispara una regla de subida
        ([10.0, 2.0, 30.0, 50.0], Change(1, 3, 48.0)),  # del valle, no de la primera
        ([2.0, 42.0], None),  # exactamente delta
    ],
)
def test_a_rise_is_measured_from_the_valley_to_a_later_peak(
    values: list[float], expected: Change | None
) -> None:
    assert detect_change(UP_40, values) == expected


def test_the_largest_change_is_reported_when_several_exceed_delta() -> None:
    # 100 → 55 ya supera delta, pero la mayor caída es del pico global al valle final.
    assert detect_change(DOWN_40, [100.0, 55.0, 90.0, 20.0]) == Change(0, 3, 80.0)
