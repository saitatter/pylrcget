from __future__ import annotations

from tools.perf.benchmark_common import median, percentile


def test_percentile_interpolates_between_samples() -> None:
    assert percentile([0, 10], 0.5) == 5


def test_percentile_empty_is_none() -> None:
    assert percentile([], 0.95) is None


def test_median_accepts_iterators() -> None:
    assert median(iter([3, 1, 2])) == 2
