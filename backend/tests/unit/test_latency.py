"""VIG-28: summarizing reading → first alert latencies against SPEC's target."""

import pytest

from willay.alerts.domain.latency import LatencySummary, percentile, summarize


def _summary(values: list[float]) -> LatencySummary:
    summary = summarize(values)
    assert summary is not None
    return summary


def test_percentiles_interpolate_between_ranks_like_postgres() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    assert percentile(values, 0.5) == 2.5
    assert percentile(values, 0.95) == pytest.approx(3.85)
    assert percentile([7.0], 0.95) == 7.0


def test_a_summary_gives_p50_p95_and_max_whatever_the_order() -> None:
    summary = _summary([0.4, 12.0, 0.2, 0.3, 0.5])
    assert (summary.count, summary.p50, summary.max) == (5, 0.4, 12.0)
    assert summary.p95 == pytest.approx(9.7)  # 0.5 + 0.8 * (12.0 - 0.5)
    assert summary.meets_target


def test_the_target_is_a_p95_under_30_seconds() -> None:
    assert not _summary([30.0] * 20).meets_target
    assert _summary([29.9] * 20).meets_target


def test_nothing_to_measure_without_alerts_sent() -> None:
    assert summarize([]) is None
