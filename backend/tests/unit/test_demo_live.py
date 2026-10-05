"""VIG-43: what the public demo plays and when."""

from datetime import UTC, datetime, timedelta

import pytest

from willay.demo import live
from willay.demo.live import Phase
from willay.ingestion.domain.simulation import MissingStationsError

STATIONS = [("RIM-CHA-01", "discharge"), ("RIM-SEU-01", "discharge"), ("RIM-CHO-01", "water_level")]


def test_the_story_lasts_nine_minutes_in_four_phases() -> None:
    assert live.TIMELINE == (
        (Phase.NORMAL, 0),
        (Phase.DROP, 60),  # one minute of normal river
        (Phase.SILENCE, 300),  # SPEC: the upstream station goes silent 4 minutes after the drop
        (Phase.DONE, 540),
    )
    assert live.DURATION_S == 540


@pytest.mark.parametrize(
    ("elapsed_s", "phase"),
    [(0, Phase.NORMAL), (59.9, Phase.NORMAL), (60, Phase.DROP), (299, Phase.DROP),
     (300, Phase.SILENCE), (539, Phase.SILENCE), (540, Phase.DONE), (5000, Phase.DONE)],
)  # fmt: skip
def test_the_phase_follows_the_timeline(elapsed_s: float, phase: Phase) -> None:
    assert live.phase_at(elapsed_s) is phase


def test_the_downstream_drop_and_the_upstream_silence_come_at_their_steps() -> None:
    plans = live.scenario_plans(STATIONS)
    before, drop, silence = live.values(plans, 5), live.values(plans, 6), live.values(plans, 30)
    assert before["RIM-CHA-01"] == pytest.approx(85, rel=0.1)
    assert drop["RIM-CHA-01"] == pytest.approx(34, rel=0.1)  # 40 % of the usual discharge
    assert drop["RIM-SEU-01"] is not None
    assert silence["RIM-SEU-01"] is None  # silent: no reading at all
    assert silence["RIM-CHO-01"] == pytest.approx(2, rel=0.1)  # the rest keep reporting


def test_the_story_needs_its_two_stations() -> None:
    with pytest.raises(MissingStationsError):
        live.scenario_plans([("RIM-CHA-01", "discharge"), ("RIM-CHO-01", "water_level")])


def test_outside_a_run_every_10_s_boundary_is_one_reading() -> None:
    now = datetime(2026, 10, 5, 15, 0, 7, tzinfo=UTC)
    step = live.normal_step(now)
    assert live.normal_time(step) == datetime(2026, 10, 5, 15, 0, 0, tzinfo=UTC)
    assert live.normal_step(now + timedelta(seconds=2)) == step
    assert live.normal_step(now + timedelta(seconds=3)) == step + 1
    normal = live.values(live.normal_plans(STATIONS), step)
    assert all(value is not None for value in normal.values())


def test_a_run_counts_its_steps_from_its_own_start() -> None:
    start = datetime(2026, 10, 5, 15, 0, 3, tzinfo=UTC)
    assert live.scenario_step(start, start) == 0
    assert live.scenario_step(start, start + timedelta(seconds=69)) == 6
    assert live.scenario_time(start, 6) == start + timedelta(seconds=60)


@pytest.mark.parametrize(
    ("after", "restore"),
    [
        # 10:00 in Lima (UTC-5): the next 04:00 is tomorrow's.
        (datetime(2026, 10, 5, 15, 0, tzinfo=UTC), datetime(2026, 10, 6, 9, 0, tzinfo=UTC)),
        # 03:59 in Lima: a minute away.
        (datetime(2026, 10, 5, 8, 59, tzinfo=UTC), datetime(2026, 10, 5, 9, 0, tzinfo=UTC)),
        # Exactly 04:00: that one is done, the next is tomorrow.
        (datetime(2026, 10, 5, 9, 0, tzinfo=UTC), datetime(2026, 10, 6, 9, 0, tzinfo=UTC)),
    ],
)
def test_the_restore_comes_at_the_next_local_hour(after: datetime, restore: datetime) -> None:
    assert live.next_restore(after, "America/Lima", 4) == restore
