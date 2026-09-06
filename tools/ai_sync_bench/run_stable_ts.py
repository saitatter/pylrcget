"""Run the isolated stable-ts research benchmark.

Run this script with the dedicated stable-ts Python interpreter. The corpus
must provide read-only audio paths and ground-truth timestamps.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
for path in (REPO_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from ui.workers.ai_sync_contracts import AlignmentOptions, AlignmentRequest  # noqa: E402
from ui.workers.ai_sync_stable_ts import StableTsResearchBackend  # noqa: E402

from tools.ai_sync_bench.corpus import BenchmarkCase, load_corpus  # noqa: E402
from tools.ai_sync_bench.metrics import (  # noqa: E402
    aggregate_samples,
    alignment_quality,
    render_report_markdown,
)


def _git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or "unknown"


def _local_segments(path: Path | None, case_id: str) -> list[dict[str, Any]]:
    if path is None:
        raise ValueError("--segments is required for stable-ts local mode")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("stable-ts segments must be an object keyed by case id")
    segments = payload.get(case_id)
    if not isinstance(segments, list):
        raise ValueError(f"No stable-ts segments found for case {case_id!r}")
    return [dict(segment) for segment in segments if isinstance(segment, dict)]


def _actual_timestamps(result, expected_count: int) -> list[float | None]:
    actual: list[float | None] = [None] * max(0, int(expected_count))
    for line in result.lines:
        index = int(line.source_line_index)
        if 0 <= index < len(actual):
            actual[index] = float(line.start) * 1000.0
    return actual


def _align_case(
    backend: StableTsResearchBackend,
    case: BenchmarkCase,
    *,
    mode: str,
    segments_path: Path | None,
) -> dict[str, Any]:
    if not case.audio_path:
        raise ValueError(f"stable-ts requires audio_path for {case.case_id}")
    extras: dict[str, object] = {"stable_ts_mode": mode}
    if mode == "local":
        extras["stable_ts_segments"] = _local_segments(segments_path, case.case_id)
    request = AlignmentRequest(
        job_id=f"stable-ts-{case.case_id}",
        audio_path=case.audio_path,
        plain_lyrics=case.lyrics,
        requested_language=case.language,
        manual_anchors=[],
        device="cpu",
        options=AlignmentOptions(extras=extras),
    )
    started = time.perf_counter()
    result = backend.align(request)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    actual = _actual_timestamps(result, len(case.lines))
    quality = alignment_quality(
        case.expected_timestamps_ms,
        actual,
        duration_seconds=case.duration_seconds,
        expected_repeat_group_ids=case.repeat_group_ids or None,
    )
    return {
        "case_id": case.case_id,
        "elapsed_ms": elapsed_ms,
        "backend_runtime_ms": result.runtime_ms,
        "coverage": result.coverage,
        "lines_aligned": len(result.lines),
        "quality": quality,
        "diagnostics": result.diagnostics,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    cases = load_corpus(args.corpus)
    model_root = args.download_root or (
        Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        / "PyLrcGet"
        / "models"
        / "stable-ts"
    )
    load_started = time.perf_counter()
    backend = StableTsResearchBackend.load(
        args.model,
        device="cpu",
        download_root=model_root,
    )
    model_load_ms = (time.perf_counter() - load_started) * 1000.0

    for _ in range(max(0, args.warmups)):
        for case in cases:
            _align_case(backend, case, mode=args.mode, segments_path=args.segments)

    samples: list[dict[str, Any]] = []
    for _ in range(max(1, args.runs)):
        started = time.perf_counter()
        cpu_started = time.process_time()
        cases_run = [
            _align_case(backend, case, mode=args.mode, segments_path=args.segments)
            for case in cases
        ]
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        cpu_time_ms = (time.process_time() - cpu_started) * 1000.0
        samples.append(
            {
                "stage_timings_ms": {
                    "total": elapsed_ms,
                    "alignment": sum(float(case["backend_runtime_ms"]) for case in cases_run),
                },
                "counters": {
                    "cases": len(cases_run),
                    "lines_aligned": sum(int(case["lines_aligned"]) for case in cases_run),
                },
                "alignment_metrics": {
                    metric: sum(
                        float(case["quality"].get(metric) or 0.0) for case in cases_run
                    )
                    / max(1, len(cases_run))
                    for metric in (
                        "coverage",
                        "offset_mean_ms",
                        "offset_p95_ms",
                        "offset_max_ms",
                    )
                },
                "resources": {"peak_rss_bytes": None},
                "cpu_time_ms": cpu_time_ms,
                "case_results": cases_run,
            }
        )

    return {
        "metadata": {
            "backend": "stable-ts-research",
            "model": args.model,
            "mode": args.mode,
            "device": "cpu",
            "corpus": str(args.corpus),
            "warmups": args.warmups,
            "runs": args.runs,
            "model_load_ms": model_load_ms,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "git_sha": _git_sha(),
            "research_only": True,
        },
        "summary": aggregate_samples(samples),
        "samples": samples,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--model", default="tiny.en")
    parser.add_argument("--mode", choices=("full", "local"), default="full")
    parser.add_argument("--segments", type=Path)
    parser.add_argument("--download-root", type=Path)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = build_report(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(
        render_report_markdown(report),
        encoding="utf-8",
    )
    print(json.dumps(report["metadata"], indent=2))
    print(render_report_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
