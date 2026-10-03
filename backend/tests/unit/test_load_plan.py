"""VIG-29: the load test's plan and its verdict against SPEC."""

from willay.loadtest.plan import SPIKE_M, THRESHOLD_M, Outcome, build_plan


def test_thirty_minutes_at_ten_seconds_is_180_rounds_with_one_spike_per_station() -> None:
    plan = build_plan(stations=50, minutes=30, interval_s=10, seed=29)
    assert plan.ticks == 180
    assert len(plan.spike_tick) == 50
    for station, spike in enumerate(plan.spike_tick):
        values = [plan.value(station, tick) for tick in range(plan.ticks)]
        # Exactly one reading above the rule's threshold: one incident per station.
        assert [v for v in values if v > THRESHOLD_M] == [SPIKE_M]
        assert values[spike] == SPIKE_M


def test_the_same_seed_gives_the_same_run() -> None:
    assert build_plan(50, 30, 10, seed=7) == build_plan(50, 30, 10, seed=7)
    assert build_plan(50, 30, 10, seed=7).spike_tick != build_plan(50, 30, 10, seed=8).spike_tick


def test_a_clean_run_passes() -> None:
    outcome = Outcome(sent=9000, rejected=0, unevaluated=0, latencies=[0.05] * 50)
    assert outcome.problems() == []


def test_each_failure_of_spec_is_named() -> None:
    outcome = Outcome(sent=9000, rejected=3, unevaluated=2, latencies=[31.0] * 50)
    assert outcome.problems() == [
        "3 of 9000 batches were not accepted",
        "2 readings were not evaluated within 120 s",
        "p95 31.000 s misses the target < 30 s",
    ]
    no_alerts = Outcome(sent=10, rejected=0, unevaluated=0, latencies=[])
    assert no_alerts.problems() == ["no incident sent an alert: there is no latency to measure"]
