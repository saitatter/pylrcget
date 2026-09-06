"""Aggregation, parity metrics and report rendering for AI sync benchmarks."""
from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


def percentile(values: Iterable[float], fraction: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, float(fraction))) * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * weight)


def summarize(values: Iterable[float | int]) -> dict[str, float | int | None]:
    items = [float(value) for value in values]
    if not items:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "max": None,
        }
    return {
        "count": len(items),
        "mean": statistics.fmean(items),
        "median": statistics.median(items),
        "p90": percentile(items, 0.90),
        "p95": percentile(items, 0.95),
        "p99": percentile(items, 0.99),
        "max": max(items),
    }


def alignment_quality(
    expected_timestamps_ms: Sequence[float],
    actual_timestamps_ms: Sequence[float | None],
    *,
    duration_seconds: float,
    expected_repeat_group_ids: Sequence[int | None] | None = None,
    actual_repeat_group_ids: Sequence[int | None] | None = None,
) -> dict[str, float | int | None]:
    """Measure timestamp health without deciding whether a match is correct.

    The benchmark corpus supplies expected timestamps.  A real backend adapter
    can provide ``None`` for missing lines; all metrics are intentionally
    backend-independent and do not alter production matching semantics.
    """
    expected = [float(value) for value in expected_timestamps_ms]
    actual = list(actual_timestamps_ms)
    total = len(expected)
    missing = sum(index >= len(actual) or actual[index] is None for index in range(total))
    paired = [
        (index, expected[index], float(actual[index]))
        for index in range(min(total, len(actual)))
        if actual[index] is not None
    ]
    errors = [abs(received - wanted) for _index, wanted, received in paired]
    valid_actual = [float(value) for value in actual if value is not None]
    duplicates = sum(
        1 for previous, current in zip(valid_actual, valid_actual[1:]) if current == previous
    )
    nonmonotonic = sum(
        1 for previous, current in zip(valid_actual, valid_actual[1:]) if current <= previous
    )

    jumps = 0
    for (_index_a, wanted_a, received_a), (_index_b, wanted_b, received_b) in zip(
        paired, paired[1:]
    ):
        expected_gap = max(1.0, wanted_b - wanted_a)
        actual_gap = received_b - received_a
        if actual_gap > max(10_000.0, expected_gap * 3.0) or actual_gap < -1_000.0:
            jumps += 1

    wrong_repeat: int | None = None
    if expected_repeat_group_ids is not None and actual_repeat_group_ids is not None:
        wrong_repeat = sum(
            expected_repeat_group_ids[index] != actual_repeat_group_ids[index]
            for index, _wanted, _received in paired
            if index < len(expected_repeat_group_ids)
            and index < len(actual_repeat_group_ids)
            and expected_repeat_group_ids[index] is not None
        )

    thresholds = {
        "offset_over_5s": sum(error > 5_000 for error in errors),
        "offset_over_10s": sum(error > 10_000 for error in errors),
        "offset_over_20s": sum(error > 20_000 for error in errors),
    }
    coverage = (len(paired) / total) if total else 1.0
    return {
        "lines_total": total,
        "lines_aligned": len(paired),
        "coverage": coverage,
        "missing": int(missing),
        "duplicate_timestamps": duplicates,
        "nonmonotonic_timestamps": nonmonotonic,
        "jumps": jumps,
        "wrong_repeat": wrong_repeat,
        "offset_mean_ms": statistics.fmean(errors) if errors else None,
        "offset_median_ms": statistics.median(errors) if errors else None,
        "offset_p95_ms": percentile(errors, 0.95),
        "offset_max_ms": max(errors) if errors else None,
        "first_line_offset_ms": errors[0] if errors else None,
        "last_line_offset_ms": errors[-1] if errors else None,
        "tail_offset_ms": (
            abs(paired[-1][2] - paired[-1][1]) if paired else None
        ),
        "duration_seconds": float(duration_seconds),
        **thresholds,
    }


def _numeric_values(mapping: Mapping[str, Any], key: str) -> list[float]:
    result: list[float] = []
    for sample in mapping.get(key, []):
        if isinstance(sample, (int, float)):
            result.append(float(sample))
    return result


def aggregate_samples(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate measured runs while retaining raw samples in the report."""
    stage_names = sorted(
        {
            stage
            for sample in samples
            for stage in (sample.get("stage_timings_ms") or {})
        }
    )
    counter_names = sorted(
        {
            name
            for sample in samples
            for name in (sample.get("counters") or {})
        }
    )
    quality_names = sorted(
        {
            name
            for sample in samples
            for name in (sample.get("alignment_metrics") or {})
            if isinstance((sample.get("alignment_metrics") or {}).get(name), (int, float))
        }
    )
    return {
        "runs": len(samples),
        "total_ms": summarize(
            (sample.get("stage_timings_ms") or {}).get("total", 0.0)
            for sample in samples
        ),
        "cpu_time_ms": summarize(sample.get("cpu_time_ms", 0.0) for sample in samples),
        "stage_timings_ms": {
            name: summarize(
                (sample.get("stage_timings_ms") or {}).get(name, 0.0)
                for sample in samples
            )
            for name in stage_names
        },
        "counters": {
            name: summarize((sample.get("counters") or {}).get(name, 0.0) for sample in samples)
            for name in counter_names
        },
        "resources": {
            "peak_rss_bytes": summarize(
                (sample.get("resources") or {}).get("peak_rss_bytes", 0.0)
                for sample in samples
                if (sample.get("resources") or {}).get("peak_rss_bytes") is not None
            ),
        },
        "alignment_metrics": {
            name: summarize(
                (sample.get("alignment_metrics") or {}).get(name, 0.0)
                for sample in samples
                if isinstance((sample.get("alignment_metrics") or {}).get(name), (int, float))
            )
            for name in quality_names
        },
    }


def compare_reports(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Return candidate-minus-baseline deltas for comparable report fields."""
    base_summary = baseline.get("summary") or {}
    candidate_summary = candidate.get("summary") or {}

    def delta(path: tuple[str, ...]) -> float | None:
        left: Any = base_summary
        right: Any = candidate_summary
        for part in path:
            left = left.get(part) if isinstance(left, Mapping) else None
            right = right.get(part) if isinstance(right, Mapping) else None
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            return None
        return float(right) - float(left)

    stage_names = set((base_summary.get("stage_timings_ms") or {})) | set(
        (candidate_summary.get("stage_timings_ms") or {})
    )
    counter_names = set((base_summary.get("counters") or {})) | set(
        (candidate_summary.get("counters") or {})
    )
    return {
        "baseline": baseline.get("metadata", {}),
        "candidate": candidate.get("metadata", {}),
        "total_ms_delta_median": delta(("total_ms", "median")),
        "total_ms_change_percent": _change_percent(
            (base_summary.get("total_ms") or {}).get("median"),
            (candidate_summary.get("total_ms") or {}).get("median"),
        ),
        "stage_median_delta_ms": {
            name: delta(("stage_timings_ms", name, "median")) for name in sorted(stage_names)
        },
        "counter_median_delta": {
            name: delta(("counters", name, "median")) for name in sorted(counter_names)
        },
    }


def _change_percent(baseline: Any, candidate: Any) -> float | None:
    if not isinstance(baseline, (int, float)) or not isinstance(candidate, (int, float)):
        return None
    if baseline == 0:
        return None
    return ((float(candidate) - float(baseline)) / float(baseline)) * 100


def render_report_markdown(report: Mapping[str, Any]) -> str:
    metadata = report.get("metadata") or {}
    summary = report.get("summary") or {}
    total = (summary.get("total_ms") or {}).get("median")
    lines = [
        "# AI Sync Benchmark",
        "",
        "This report is generated by `tools/ai_sync_bench/run_benchmark.py`.",
        "",
        "## Run metadata",
        "",
    ]
    for key, value in metadata.items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- measured runs: `{summary.get('runs', 0)}`",
            f"- median total: `{_format_ms(total)}`",
            f"- p95 total: `{_format_ms((summary.get('total_ms') or {}).get('p95'))}`",
            "",
            "### Stage timings",
            "",
            "| Stage | Median | P95 | Max |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for name, values in (summary.get("stage_timings_ms") or {}).items():
        lines.append(
            f"| `{name}` | {_format_ms(values.get('median'))} | "
            f"{_format_ms(values.get('p95'))} | {_format_ms(values.get('max'))} |"
        )
    lines.extend(["", "### Counters", "", "| Counter | Median | Max |", "| --- | ---: | ---: |"])
    for name, values in (summary.get("counters") or {}).items():
        lines.append(
            f"| `{name}` | {_format_number(values.get('median'))} | "
            f"{_format_number(values.get('max'))} |"
        )
    lines.extend(["", "### Alignment metrics", "", "| Metric | Median | Max |", "| --- | ---: | ---: |"])
    for name, values in (summary.get("alignment_metrics") or {}).items():
        lines.append(
            f"| `{name}` | {_format_number(values.get('median'))} | "
            f"{_format_number(values.get('max'))} |"
        )
    lines.append("")
    return "\n".join(lines)


def _format_ms(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):,.2f} ms"


def _format_number(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):,.3f}"


__all__ = [
    "aggregate_samples",
    "alignment_quality",
    "compare_reports",
    "percentile",
    "render_report_markdown",
    "summarize",
]
