"""VIG-27: a draft rule replayed over past readings marks where incidents would have opened."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from willay.rules.application.preview import (
    MAX_POINTS,
    PreviewStation,
    preview_rule,
)
from willay.rules.domain.preview import (
    Firing,
    Point,
    rate_of_change_firings,
    silence_firings,
    threshold_firings,
)
from willay.rules.domain.rate_of_change import Direction, RateOfChangeParams
from willay.rules.domain.rules import InvalidRuleError, RuleType
from willay.rules.domain.threshold import Operator, ThresholdParams
from willay.shared.clock import FakeClock

T0 = datetime(2026, 12, 22, 9, 0, tzinfo=UTC)
ORG, ZONE = uuid4(), uuid4()


def _series(*values: float, every_s: int = 60, start: datetime = T0) -> list[Point]:
    return [Point(start + timedelta(seconds=every_s * i), v) for i, v in enumerate(values)]


def test_a_threshold_fires_once_per_run_of_n_readings_out_of_bounds() -> None:
    readings = _series(1, 5, 6, 7, 2, 5, 6)
    firings = threshold_firings(ThresholdParams(Operator.GT, 4.0, 2), readings, since=T0)
    # The run 5, 6, 7 opens one incident at its 2nd reading; 7 only adds to it.
    assert firings == [Firing(readings[2].at, 6), Firing(readings[6].at, 6)]


def test_a_threshold_counts_readings_from_before_the_period_but_only_marks_inside_it() -> None:
    readings = _series(5, 6, 7, 2, 5)
    since = readings[2].at
    params = ThresholdParams(Operator.GT, 4.0, 3)
    assert threshold_firings(params, readings, since) == [Firing(since, 7)]
    assert threshold_firings(params, readings, readings[3].at) == []  # it opened before


def test_a_drop_fires_once_even_if_it_partly_recovers_within_the_window() -> None:
    # The demo's damming: 85 → 34 m3/s and partly back up, then a second drop later on.
    readings = _series(85, 84, 34, 60, 62, 61, 61, 61, 61, 61, 61, 61, 61, 10, every_s=60)
    params = RateOfChangeParams(Direction.DOWN, 40.0, 5)
    firings = rate_of_change_firings(params, readings, since=T0)
    assert firings == [Firing(readings[2].at, 34), Firing(readings[13].at, 10)]


def test_a_rise_does_not_fire_a_drop_rule() -> None:
    readings = _series(10, 60, 90)
    params = RateOfChangeParams(Direction.DOWN, 40.0, 10)
    assert rate_of_change_firings(params, readings, since=T0) == []
    rise = RateOfChangeParams(Direction.UP, 40.0, 10)
    assert rate_of_change_firings(rise, readings, since=T0) == [Firing(readings[1].at, 60)]


def test_silence_fires_when_a_gap_reaches_k_times_the_interval() -> None:
    threshold = timedelta(seconds=30)
    since, until = T0, T0 + timedelta(hours=1)
    received = [
        T0 - timedelta(minutes=5),  # last report before the period: already silent at T0
        T0 + timedelta(seconds=10),
        T0 + timedelta(seconds=20),
        T0 + timedelta(seconds=60),  # a 40 s gap: silent from second 50
        T0 + timedelta(seconds=70),  # then quiet until `until`
    ]
    assert silence_firings(threshold, received, since, until) == [
        Firing(T0 + timedelta(seconds=50), None),
        Firing(T0 + timedelta(seconds=100), None),
    ]


def test_a_station_that_never_reported_is_not_silent() -> None:
    assert silence_firings(timedelta(seconds=30), [], T0, T0 + timedelta(hours=1)) == []


class FakePreviews:
    def __init__(self, *stations: PreviewStation, points: int = 3) -> None:
        self.by_id = {s.id: s for s in stations}
        self.points = points

    async def zone_exists(self, organization_id: UUID, zone_id: UUID) -> bool:
        return zone_id == ZONE

    async def stations(
        self, organization_id: UUID, zone_id: UUID, station_id: UUID | None
    ) -> list[PreviewStation]:
        if station_id is None:
            return list(self.by_id.values())
        return [self.by_id[station_id]] if station_id in self.by_id else []

    async def readings(
        self, station_id: UUID, since: datetime, until: datetime, limit: int
    ) -> list[Point]:
        every = (until - since) / self.points
        return [Point(until - every * i, 1.0) for i in range(min(self.points, limit))][::-1]

    async def last_reported_before(self, station_id: UUID, moment: datetime) -> datetime | None:
        return moment - timedelta(seconds=5)

    async def reported(self, station_id: UUID, since: datetime, until: datetime) -> list[datetime]:
        return []


def _station(code: str) -> PreviewStation:
    return PreviewStation(uuid4(), code, code, "m3/s", 10, 3)


async def test_a_zone_wide_silence_rule_is_previewed_on_every_station_of_the_zone() -> None:
    stations = FakePreviews(_station("A"), _station("B"))
    preview = await preview_rule(
        ORG, RuleType.SILENCE, ZONE, None, {}, repository=stations, clock=FakeClock(T0)
    )
    assert [p.station.code for p in preview.stations] == ["A", "B"]
    # Quiet since 5 s before the period: silent 25 s into it, at K * interval = 30 s.
    assert preview.stations[0].firings == [Firing(preview.since + timedelta(seconds=25), None)]
    assert preview.until - preview.since == timedelta(hours=24)


@pytest.mark.parametrize(
    ("rule_type", "zone", "station", "field"),
    [
        (RuleType.THRESHOLD, ZONE, None, "station_id"),
        (RuleType.THRESHOLD, uuid4(), "known", "zone_id"),
        (RuleType.THRESHOLD, ZONE, "unknown", "station_id"),  # not a station of that zone
    ],
)
async def test_an_invalid_draft_names_its_field(
    rule_type: RuleType, zone: UUID, station: str | None, field: str
) -> None:
    known = _station("A")
    station_id = {"known": known.id, "unknown": uuid4(), None: None}[station]
    with pytest.raises(InvalidRuleError) as caught:
        await preview_rule(
            ORG, rule_type, zone, station_id, {"operator": "gt", "value": 1, "consecutive": 1},
            repository=FakePreviews(known), clock=FakeClock(T0),
        )  # fmt: skip
    assert caught.value.field == field


async def test_a_day_with_too_many_readings_says_it_left_the_oldest_out() -> None:
    station = _station("A")
    preview = await preview_rule(
        ORG, RuleType.THRESHOLD, ZONE, station.id,
        {"operator": "gt", "value": 5, "consecutive": 1},
        repository=FakePreviews(station, points=MAX_POINTS + 10), clock=FakeClock(T0),
    )  # fmt: skip
    assert preview.stations[0].truncated is True
    assert len(preview.stations[0].readings) <= MAX_POINTS
