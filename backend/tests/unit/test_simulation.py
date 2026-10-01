import pytest

from vigia.ingestion.domain.simulation import (
    BASELINES,
    DROP_FACTOR,
    RIMAC_DOWNSTREAM,
    RIMAC_UPSTREAM,
    RISE_FACTOR,
    RISE_STEPS,
    Behavior,
    MissingStationsError,
    Scenario,
    StationPlan,
    build_plan,
    value_at,
)

DISCHARGE = StationPlan("RIM-CHA-01", "discharge", Behavior.NORMAL)
# Noise tolerance: 5 sigmas over the ±2 % relative noise.
NOISE = 0.10


def _series(plan: StationPlan, seed: int, steps: int = 50) -> list[float | None]:
    return [value_at(plan, seed, step) for step in range(steps)]


def test_same_seed_gives_the_same_series() -> None:
    assert _series(DISCHARGE, 42) == _series(DISCHARGE, 42)


def test_series_is_reproducible_across_processes_and_machines() -> None:
    # Golden values: random.Random seeded with a string uses SHA-512, not hash(), so it does
    # not change with PYTHONHASHSEED or across machines. If this test fails, the recorded
    # demo is no longer reproducible with the same seed.
    assert _series(DISCHARGE, 42, 3) == [85.813, 85.33, 82.858]


def test_different_seeds_give_different_series() -> None:
    assert _series(DISCHARGE, 42) != _series(DISCHARGE, 43)


def test_a_step_does_not_depend_on_what_was_computed_before() -> None:
    assert value_at(DISCHARGE, 42, 37) == _series(DISCHARGE, 42)[37]


def test_stations_with_the_same_seed_are_not_copies_of_each_other() -> None:
    other = StationPlan("RIM-HUA-01", "discharge", Behavior.NORMAL)
    assert _series(DISCHARGE, 42) != _series(other, 42)


def test_normal_stays_around_the_baseline() -> None:
    base = BASELINES["discharge"]
    assert all(abs(v - base) < base * NOISE for v in _series(DISCHARGE, 7) if v is not None)


def test_drop_falls_by_more_than_the_demo_rule_delta_at_the_event_step() -> None:
    plan = StationPlan("RIM-CHA-01", "discharge", Behavior.DROP, event_step=10)
    before, after = value_at(plan, 1, 9), value_at(plan, 1, 10)
    assert before is not None
    assert after is not None
    assert abs(after - BASELINES["discharge"] * DROP_FACTOR) < BASELINES["discharge"] * NOISE
    # The seed's rate-of-change rule needs a drop greater than 40 m3/s.
    assert before - after > 40.0


def test_rise_ramps_up_to_twice_the_baseline_and_crosses_the_seed_threshold() -> None:
    plan = StationPlan("RIM-CHO-01", "water_level", Behavior.RISE, event_step=5)
    start, end = value_at(plan, 3, 5), value_at(plan, 3, 5 + RISE_STEPS + 10)
    assert start is not None
    assert end is not None
    assert start < 2.2
    assert abs(end - BASELINES["water_level"] * RISE_FACTOR) < 0.4
    assert end > 3.5  # threshold of the RIM-CHO-01 rule in the seed


def test_silence_stops_emitting_at_the_event_step() -> None:
    plan = StationPlan("RIM-SEU-01", "discharge", Behavior.SILENCE, event_step=3)
    assert [v is None for v in _series(plan, 1, 6)] == [False, False, False, True, True, True]


def test_rainfall_never_goes_negative() -> None:
    plan = StationPlan("RIM-CHO-02", "rainfall", Behavior.DROP)
    assert all(v is not None and v >= 0 for v in _series(plan, 99, 200))


def test_simple_scenarios_apply_the_same_behavior_to_every_station() -> None:
    stations = [("A", "discharge"), ("B", "water_level")]
    plan = build_plan(Scenario.DROP, stations, event_step=6, interval_s=10)
    assert plan == [
        StationPlan("A", "discharge", Behavior.DROP, 6),
        StationPlan("B", "water_level", Behavior.DROP, 6),
    ]


def test_rimac_scenario_drops_downstream_then_silences_upstream_four_minutes_later() -> None:
    stations = [(RIMAC_UPSTREAM, "discharge"), (RIMAC_DOWNSTREAM, "discharge"), ("X", "rainfall")]
    plan = {p.code: p for p in build_plan(Scenario.RIMAC, stations, event_step=6, interval_s=10)}

    assert plan[RIMAC_DOWNSTREAM] == StationPlan(RIMAC_DOWNSTREAM, "discharge", Behavior.DROP, 6)
    assert plan[RIMAC_UPSTREAM] == StationPlan(RIMAC_UPSTREAM, "discharge", Behavior.SILENCE, 30)
    assert plan["X"].behavior is Behavior.NORMAL


def test_rimac_scenario_needs_both_demo_stations() -> None:
    with pytest.raises(MissingStationsError, match=RIMAC_UPSTREAM):
        build_plan(Scenario.RIMAC, [(RIMAC_DOWNSTREAM, "discharge")], event_step=0, interval_s=10)
