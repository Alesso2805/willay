from typing import Any

import pytest

from vigia.rules.domain.errors import InvalidRuleParamsError
from vigia.rules.domain.threshold import (
    Operator,
    ThresholdParams,
    fires,
    parse_threshold,
)

GT_35 = ThresholdParams(Operator.GT, 3.5, 2)


def test_seed_params_are_parsed() -> None:
    assert parse_threshold({"operator": "gt", "value": 3.5, "consecutive": 2}) == GT_35
    assert parse_threshold({"operator": "le", "value": 1, "consecutive": 1}).value == 1.0


@pytest.mark.parametrize(
    "raw",
    [
        {"value": 3.5, "consecutive": 2},
        {"operator": "between", "value": 3.5, "consecutive": 2},
        {"operator": "gt", "value": "alto", "consecutive": 2},
        {"operator": "gt", "value": True, "consecutive": 2},
        {"operator": "gt", "value": 3.5, "consecutive": 0},
        {"operator": "gt", "value": 3.5, "consecutive": 61},
        {"operator": "gt", "value": 3.5, "consecutive": 2.5},
        {"operator": "gt", "value": 3.5, "consecutive": True},
    ],
)
def test_invalid_params_are_rejected(raw: dict[str, Any]) -> None:
    with pytest.raises(InvalidRuleParamsError):
        parse_threshold(raw)


@pytest.mark.parametrize(
    ("operator", "reading", "breached"),
    [
        (Operator.GT, 3.5, False),  # frontera: igual no supera
        (Operator.GT, 3.5000001, True),
        (Operator.GE, 3.5, True),
        (Operator.GE, 3.4999999, False),
        (Operator.LT, 3.5, False),
        (Operator.LT, 3.4999999, True),
        (Operator.LE, 3.5, True),
        (Operator.LE, 3.5000001, False),
    ],
)
def test_limit_is_exact_at_the_boundary(operator: Operator, reading: float, breached: bool) -> None:
    assert ThresholdParams(operator, 3.5, 1).breached_by(reading) is breached


@pytest.mark.parametrize(
    ("latest_first", "expected"),
    [
        ([3.7, 3.6], True),  # las dos más recientes superan
        ([3.7, 3.6, 1.0], True),  # lo anterior a la ventana no importa
        ([3.7], False),  # aún no hay N lecturas
        ([3.7, 3.5], False),  # la segunda está justo en el límite (gt)
        ([3.4, 3.9], False),  # la más reciente ya volvió dentro
        ([], False),
    ],
)
def test_fires_only_with_n_consecutive_breaches(latest_first: list[float], expected: bool) -> None:
    assert fires(GT_35, latest_first) is expected
