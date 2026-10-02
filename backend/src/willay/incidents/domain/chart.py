"""The readings shown with an incident (VIG-26): which window, from where, and which line.

The window tells the story of the opening: an hour before it (what led to it) and up to two
hours after (whether it kept worsening). Readings expire (180-day retention), but the `opened`
event keeps a copy of those that fired the rule: when the window has no readings left, that
copy is shown instead, so the chart never goes blank for an old incident.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

BEFORE_OPENING = timedelta(hours=1)
AFTER_OPENING = timedelta(hours=2)

Source = Literal["readings", "evidence"]


@dataclass(frozen=True)
class Point:
    measured_at: datetime
    value: float


@dataclass(frozen=True)
class Threshold:
    operator: str  # gt, ge, lt, le
    value: float


def readings_window(opened_at: datetime, now: datetime) -> tuple[datetime, datetime]:
    return opened_at - BEFORE_OPENING, min(now, opened_at + AFTER_OPENING)


def evidence(opened_payload: Mapping[str, Any]) -> list[Point]:
    """The readings copied into the `opened` event; an odd entry is skipped, never fatal."""
    points = []
    for raw in opened_payload.get("readings") or []:
        try:
            points.append(Point(datetime.fromisoformat(raw["measured_at"]), float(raw["value"])))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(points, key=lambda p: p.measured_at)


def series(stored: Sequence[Point], copy: Sequence[Point]) -> tuple[Source, list[Point]]:
    """The stored readings if the window still has any; otherwise the evidence copy."""
    if stored or not copy:
        return "readings", list(stored)
    return "evidence", list(copy)


def threshold(opened_payload: Mapping[str, Any]) -> Threshold | None:
    """A threshold rule's boundary, to draw as a line; other rules have none."""
    params = opened_payload.get("rule_params") or {}
    if opened_payload.get("rule_type") != "threshold":
        return None
    try:
        return Threshold(str(params["operator"]), float(params["value"]))
    except (KeyError, TypeError, ValueError):
        return None
