from __future__ import annotations

import pytest

from tests import test_support as _test_support  # noqa: F401

from tools.ai_sync_bench.corpus import build_corpus, load_corpus
from tools.ai_sync_bench.metrics import alignment_quality, percentile, summarize
from ui.workers.ai_sync_profiler import StageProfiler


def test_stage_profiler_accumulates_stage_and_counter_data() -> None:
    ticks = iter([0, 1_000_000, 3_000_000, 8_000_000])
    cpu_ticks = iter([0.0, 0.002, 0.006])
    profiler = StageProfiler(
        clock=lambda: next(ticks),
        cpu_clock=lambda: next(cpu_ticks),
        resource_sampler=lambda: {"peak_rss_bytes": 123},
    )

    with profiler.stage("asr"):
        profiler.increment("asr_count")
    profiler.increment("asr_count", 2)
    result = profiler.finish()

    assert result["stage_timings_ms"]["asr"] == 2.0
    assert result["stage_timings_ms"]["total"] == 8.0
    assert result["counters"] == {"asr_count": 3}
    assert result["resources"] == {"peak_rss_bytes": 123}
    assert result["cpu_time_ms"] == 2.0


def test_stage_profiler_observations_are_json_friendly() -> None:
    profiler = StageProfiler(resource_sampler=lambda: {})
    profiler.observe("latency_ms", 12)
    profiler.observe("latency_ms", 18)

    assert profiler.finish()["observations"] == {"latency_ms": [12.0, 18.0]}


def test_metrics_report_missing_offsets_and_nonmonotonic_timestamps() -> None:
    result = alignment_quality(
        [0, 10_000, 20_000, 30_000],
        [0, None, 15_000, 15_000],
        duration_seconds=40,
    )

    assert result["coverage"] == 0.75
    assert result["missing"] == 1
    assert result["duplicate_timestamps"] == 1
    assert result["nonmonotonic_timestamps"] == 1
    assert result["offset_over_5s"] == 1


def test_metrics_can_measure_wrong_repeat_groups_when_backend_exposes_them() -> None:
    result = alignment_quality(
        [0, 1000],
        [0, 1000],
        duration_seconds=2,
        expected_repeat_group_ids=[4, 4],
        actual_repeat_group_ids=[4, 9],
    )

    assert result["wrong_repeat"] == 1


def test_percentile_and_summary_are_stable() -> None:
    assert percentile([0, 10], 0.5) == 5
    result = summarize([1, 2, 3, 4])
    assert result["median"] == 2.5
    assert result["p95"] == pytest.approx(3.85)


def test_builtin_corpus_has_expected_fixture_size() -> None:
    cases = build_corpus(profile="smoke")

    assert len(cases) == 5
    assert all(len(case.lines) == len(case.expected_timestamps_ms) for case in cases)


def test_custom_corpus_round_trips(tmp_path) -> None:
    path = tmp_path / "corpus.json"
    path.write_text(
        '{"cases": [{"id": "x", "language": "en", "lines": ["a"], '
        '"expected_timestamps_ms": [1000], "duration_seconds": 2}]}',
        encoding="utf-8",
    )

    cases = load_corpus(path)

    assert cases[0].case_id == "x"
    assert cases[0].lyrics == "a"
