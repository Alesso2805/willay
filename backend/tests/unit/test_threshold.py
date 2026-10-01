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
        {"operator": "gt", "value": "high", "consecutive": 2},
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
        (Operator.GT, 3.5, False),  # boundary: equal does not exceed
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
        ([3.7, 3.6], True),  # the two latest exceed
        ([3.7, 3.6, 1.0], True),  # readings before the window do not matter
        ([3.7], False),  # fewer than N readings so far
        ([3.7, 3.5], False),  # the second sits exactly on the limit (gt)
        ([3.4, 3.9], False),  # the latest is already back within the limit
        ([], False),
    ],
)
def test_fires_only_with_n_consecutive_breaches(latest_first: list[float], expected: bool) -> None:
    assert fires(GT_35, latest_first) is expected
