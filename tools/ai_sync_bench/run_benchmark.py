"""Run a deterministic AI sync benchmark or an optional production adapter.

The default ``synthetic`` backend validates the harness without importing
WhisperX, loading a model, touching audio files or making network requests.
The ``current`` backend is intentionally opt-in and requires a custom corpus
whose cases contain ``audio_path`` values.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ui.workers.ai_sync_profiler import StageProfiler  # noqa: E402

if __package__:
    from .corpus import BenchmarkCase, build_corpus, load_corpus  # noqa: E402
    from .metrics import aggregate_samples, alignment_quality, render_report_markdown  # noqa: E402
else:  # Direct ``python tools/ai_sync_bench/run_benchmark.py`` invocation.
    from tools.ai_sync_bench.corpus import BenchmarkCase, build_corpus, load_corpus  # noqa: E402
    from tools.ai_sync_bench.metrics import (  # noqa: E402
        aggregate_samples,
        alignment_quality,
        render_report_markdown,
    )


class SyntheticBackend:
    name = "synthetic"

    def __init__(self, jitter_ms: float = 0.0) -> None:
        self.jitter_ms = float(jitter_ms)

    def align(self, case: BenchmarkCase) -> tuple[dict[str, Any], dict[str, Any]]:
        profiler = StageProfiler(metadata={"backend": self.name, "case_id": case.case_id})
        with profiler.stage("process_startup"):
            profiler.increment("process_starts")
        with profiler.stage("runtime_initialization"):
            profiler.increment("runtime_initializations")
        with profiler.stage("backend_import"):
            _stable_fixture_work(case)
            profiler.increment("backend_imports")
        with profiler.stage("model_load"):
            profiler.increment("model_loads")
        with profiler.stage("audio_decode_resample"):
            profiler.increment("audio_decode_count")
        with profiler.stage("language_detection"):
            profiler.increment("language_detection_count")
        with profiler.stage("g2p"):
            profiler.increment("g2p_count")
        with profiler.stage("asr"):
            profiler.increment("asr_count")
        with profiler.stage("forced_alignment"):
            profiler.increment("alignment_count")
        with profiler.stage("viterbi"):
            profiler.increment("viterbi_count")
        with profiler.stage("lrc_render"):
            profiler.increment("lrc_render_count")
        actual = [timestamp + self.jitter_ms for timestamp in case.expected_timestamps_ms]
        return actual, profiler.finish()


class _Emitter:
    def __init__(self, callback):
        self._callback = callback

    def emit(self, *args) -> None:
        self._callback(*args)


class _CurrentWorkerContext:
    """Minimal non-Qt context for direct production-pipeline measurements."""

    _PROGRESS_MARKER = "__AI_SYNC_PROGRESS__"

    def __init__(self, case: BenchmarkCase, *, profiler: StageProfiler, device: str) -> None:
        if not case.audio_path:
            raise ValueError(f"Current backend requires audio_path for {case.case_id}")
        self.audio_path = case.audio_path
        self.plain_lyrics = case.lyrics
        self.manual_anchors: list[dict[str, Any]] = []
        self.whisper_model = "base"
        self._device = device
        self._language = case.language
        self._enable_fuzzy = True
        self._fuzzy_threshold = 60
        self._fuzzy_window_words = 12
        self._enable_demucs_candidate = False
        self.profiler = profiler
        self.completed_result: tuple[bool, str, str] | None = None
        self.progress = _Emitter(lambda message: None)
        self.completed = _Emitter(self._completed)
        self._active_stage: tuple[str, int] | None = None

    def _completed(self, ok: bool, message: str, output: str) -> None:
        self.completed_result = (bool(ok), str(message), str(output))

    def _resolve_device(self) -> str:
        if self._device != "auto":
            return self._device
        return "cpu"

    def _emit_stage(self, current: int, total: int, message: str) -> None:
        self.profiler.set_metadata("last_progress", message)
        self._record_stage_from_message(message)

    def _record_stage_from_message(self, message: str) -> None:
        lowered = message.casefold()
        mapping = (
            ("loading audio", "audio_decode_resample"),
            ("loading whisperx", "model_load"),
            ("transcrib", "asr"),
            ("forced", "forced_alignment"),
            ("aligning lyric", "viterbi"),
            ("checking speech", "relaxed_vad_retry"),
            ("building synced", "lrc_render"),
            ("finalizing", "lrc_render"),
        )
        for needle, stage_name in mapping:
            if needle in lowered:
                self.profiler.increment(f"{stage_name}_progress_events")
                self.profiler.set_metadata("last_stage", stage_name)
                return

    def isInterruptionRequested(self) -> bool:
        return False


class CurrentPipelineBackend:
    name = "current"

    def __init__(self, *, device: str = "cpu") -> None:
        self.device = device

    def align(self, case: BenchmarkCase) -> tuple[list[float | None], dict[str, Any]]:
        from ui.workers.ai_sync_pipeline import run_ai_sync_pipeline

        profiler = StageProfiler(metadata={"backend": self.name, "case_id": case.case_id})
        with profiler.stage("process_startup"):
            profiler.increment("process_starts")
        with profiler.stage("runtime_initialization"):
            context = _CurrentWorkerContext(case, profiler=profiler, device=self.device)
        with profiler.stage("backend_import"):
            run_ai_sync_pipeline(context)
        result = context.completed_result
        if result is None:
            raise RuntimeError("Current AI pipeline did not emit a completed result")
        ok, message, output = result
        profiler.set_metadata("success", ok)
        profiler.set_metadata("message", message)
        profiler.increment("alignment_count")
        actual = _parse_lrc_timestamps(output) if ok else [None] * len(case.lines)
        return actual, profiler.finish()


def _stable_fixture_work(case: BenchmarkCase) -> None:
    # A tiny deterministic operation makes the fixture backend exercise the
    # same profiler paths on every machine without pretending to be model work.
    digest = 0
    for line in case.lines:
        for character in line:
            digest = ((digest * 33) ^ ord(character)) & 0xFFFFFFFF
    if digest == -1:  # pragma: no cover - keeps the loop observable to linters.
        raise AssertionError("unreachable fixture digest")


_LRC_TIMESTAMP = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")


def _parse_lrc_timestamps(lrc: str) -> list[float | None]:
    timestamps: list[float] = []
    for line in str(lrc or "").splitlines():
        match = _LRC_TIMESTAMP.search(line)
        if match:
            timestamps.append((int(match.group(1)) * 60 + float(match.group(2))) * 1000)
    return timestamps


def _resolve_cases(args: argparse.Namespace) -> list[BenchmarkCase]:
    if args.corpus:
        return load_corpus(args.corpus)
    return build_corpus(
        profile=args.profile,
        count=args.count,
        duplicate_every=args.duplicate_every,
    )


def _run_once(
    backend: SyntheticBackend | CurrentPipelineBackend,
    cases: list[BenchmarkCase],
) -> dict[str, Any]:
    started = time.perf_counter_ns()
    case_snapshots: list[dict[str, Any]] = []
    quality_samples: list[dict[str, Any]] = []
    for case in cases:
        actual, snapshot = backend.align(case)
        case_snapshots.append(snapshot)
        quality_samples.append(
            alignment_quality(
                case.expected_timestamps_ms,
                actual,
                duration_seconds=case.duration_seconds,
                expected_repeat_group_ids=case.repeat_group_ids or None,
                actual_repeat_group_ids=(
                    case.repeat_group_ids or None
                    if isinstance(backend, SyntheticBackend)
                    else None
                ),
            )
        )

    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    stage_totals: dict[str, float] = {}
    counters: dict[str, float] = {}
    resource_values: list[int] = []
    cpu_time_ms = 0.0
    for snapshot in case_snapshots:
        for name, value in (snapshot.get("stage_timings_ms") or {}).items():
            stage_totals[name] = stage_totals.get(name, 0.0) + float(value)
        for name, value in (snapshot.get("counters") or {}).items():
            counters[name] = counters.get(name, 0.0) + float(value)
        cpu_time_ms += float(snapshot.get("cpu_time_ms") or 0.0)
        rss = (snapshot.get("resources") or {}).get("peak_rss_bytes")
        if isinstance(rss, (int, float)):
            resource_values.append(int(rss))
    stage_totals["total"] = elapsed_ms

    quality: dict[str, float] = {}
    for name in {name for sample in quality_samples for name in sample}:
        values = [sample[name] for sample in quality_samples if isinstance(sample.get(name), (int, float))]
        if values:
            quality[name] = sum(float(value) for value in values) / len(values)
    return {
        "stage_timings_ms": stage_totals,
        "counters": counters,
        "resources": {"peak_rss_bytes": max(resource_values) if resource_values else None},
        "cpu_time_ms": cpu_time_ms,
        "alignment_metrics": quality,
        "case_results": [
            {"id": case.case_id, "metrics": quality_sample}
            for case, quality_sample in zip(cases, quality_samples)
        ],
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    cases = _resolve_cases(args)
    if args.backend == "synthetic":
        backend: SyntheticBackend | CurrentPipelineBackend = SyntheticBackend(args.jitter_ms)
    else:
        backend = CurrentPipelineBackend(device=args.device)
    for _ in range(max(0, args.warmups)):
        _run_once(backend, cases)
    samples = [_run_once(backend, cases) for _ in range(max(1, args.runs))]
    metadata = {
        "schema_version": 1,
        "backend": args.backend,
        "corpus": str(args.corpus or args.profile),
        "case_count": len(cases),
        "warmups": max(0, args.warmups),
        "measured_runs": max(1, args.runs),
        "device": args.device,
        "python": sys.version.split()[0],
        "os": os.name,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "commit": _git_commit(),
        "synthetic_note": (
            "Synthetic timings validate the harness only; use --backend current for model numbers."
            if args.backend == "synthetic"
            else "Current production pipeline adapter; stage buckets are inferred from progress events."
        ),
    }
    return {
        "schema_version": 1,
        "metadata": metadata,
        "summary": aggregate_samples(samples),
        "samples": samples,
    }


def _git_commit() -> str:
    try:
        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(render_report_markdown(report), encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--backend", choices=("synthetic", "current"), default="synthetic")
    result.add_argument("--corpus", type=Path, help="JSON corpus; required for real audio paths")
    result.add_argument("--profile", choices=("smoke", "small", "medium"), default="smoke")
    result.add_argument("--count", type=int)
    result.add_argument("--duplicate-every", type=int, default=0)
    result.add_argument("--jitter-ms", type=float, default=0.0)
    result.add_argument("--device", default="cpu")
    result.add_argument("--warmups", type=int, default=2)
    result.add_argument("--runs", type=int, default=3)
    result.add_argument("--output", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    report = build_report(args)
    output = args.output or (
        REPO_ROOT / "benchmarks" / "ai_sync" / f"{args.backend}-{args.profile}.json"
    )
    _write_report(report, output)
    print(render_report_markdown(report))
    print(f"JSON report: {output}")
    print(f"Markdown report: {output.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
