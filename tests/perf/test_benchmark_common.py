from __future__ import annotations

from pathlib import Path

from tools.perf.benchmark_common import median, percentile
from tools.perf import benchmark_scan


def test_percentile_interpolates_between_samples() -> None:
    assert percentile([0, 10], 0.5) == 5


def test_percentile_empty_is_none() -> None:
    assert percentile([], 0.95) is None


def test_median_accepts_iterators() -> None:
    assert median(iter([3, 1, 2])) == 2


def test_scan_read_only_source_does_not_copy_library(monkeypatch, tmp_path) -> None:
    calls = []

    def fake_run_scan(library_root, **kwargs):
        calls.append((library_root, kwargs))
        return {"total_ms": 1}

    def fail_copytree(*_args, **_kwargs):
        raise AssertionError("read-only source mode must not copy or mutate the source")

    monkeypatch.setattr(benchmark_scan, "_run_scan", fake_run_scan)
    monkeypatch.setattr(benchmark_scan.shutil, "copytree", fail_copytree)
    source = tmp_path / "library"
    source.mkdir()

    benchmark_scan._one_sample(
        source,
        scenario="unchanged",
        worker_count=4,
        fraction=0.01,
        suffix=".lrc",
        seed=42,
        read_only_source=True,
    )

    assert len(calls) == 2
    assert all(Path(call[0]) == source for call in calls)
