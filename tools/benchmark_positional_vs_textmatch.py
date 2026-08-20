#!/usr/bin/env python3
"""Benchmark the production English lyrics-aligner pipeline on five reference tracks.

This intentionally calls the same selector as ``AiSyncWorker``:

1. lyrics-aligner on the original mix;
2. optional Demucs vocal candidate;
3. no-ground-truth candidate selection;
4. positional evaluation against the reference LRC.

The reference LRC files are used only for evaluation. They are never passed to
the runtime synchronizer.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MUSIC = Path(r"C:\Users\andrvoicu\Downloads\music_test")
OUT = REPO / "tools" / "whisperx_test_output"
REPORT = OUT / "lyrics_aligner_pipeline_benchmark.json"

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.ui.workers.ai_sync_worker import (  # noqa: E402
    _align_with_optional_demucs,
)


_LRC_RE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")


def parse_lrc(path: Path) -> list[tuple[float, str]]:
    lines: list[tuple[float, str]] = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = _LRC_RE.match(raw.strip())
        if match and match.group(3).strip():
            lines.append(
                (
                    int(match.group(1)) * 60 + float(match.group(2)),
                    match.group(3).strip(),
                )
            )
    return lines


def plain_lyrics(stem: str, ground_truth: list[tuple[float, str]]) -> str:
    txt_path = MUSIC / f"{stem}.txt"
    if txt_path.exists():
        return "\n".join(
            line.strip()
            for line in txt_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            if line.strip()
        )
    return "\n".join(text for _timestamp, text in ground_truth)


def parse_lrc_text(raw_lrc: str) -> list[tuple[float, str]]:
    lines: list[tuple[float, str]] = []
    for raw in raw_lrc.splitlines():
        match = _LRC_RE.match(raw.strip())
        if match and match.group(3).strip():
            lines.append(
                (
                    int(match.group(1)) * 60 + float(match.group(2)),
                    match.group(3).strip(),
                )
            )
    return lines


def summarize(errors: list[float]) -> dict[str, float | int | None]:
    if not errors:
        return {"mean": None, "p95": None, "max": None, "n": 0}
    ordered = sorted(errors)
    return {
        "mean": round(statistics.mean(errors), 2),
        "p95": round(ordered[round((len(ordered) - 1) * 0.95)], 2),
        "max": round(max(errors), 2),
        "n": len(errors),
    }


def evaluate(
    ground_truth: list[tuple[float, str]],
    prediction: list[tuple[float, str]],
) -> dict[str, float | int | None]:
    count = min(len(ground_truth), len(prediction))
    errors = [
        abs(ground_truth[index][0] - prediction[index][0])
        for index in range(count)
    ]
    result = summarize(errors)
    result.update({"gt_lines": len(ground_truth), "pred_lines": len(prediction)})
    return result


def main() -> int:
    try:
        import torch
    except ImportError as exc:
        print(f"Missing torch: {exc}", file=sys.stderr)
        return 2

    if not MUSIC.is_dir():
        print(f"Reference directory not found: {MUSIC}", file=sys.stderr)
        return 2

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tracks = sorted(MUSIC.glob("*.flac"))
    if len(tracks) != 5:
        print(f"Expected 5 reference tracks, found {len(tracks)}.", file=sys.stderr)
        return 2

    print(f"Production lyrics-aligner benchmark ({device}, Demucs candidate enabled)")
    results: list[dict[str, object]] = []
    all_errors: list[float] = []

    for audio_path in tracks:
        stem = audio_path.stem
        ground_truth = parse_lrc(MUSIC / f"{stem}.lrc")
        lyrics = plain_lyrics(stem, ground_truth)
        print(f"\n===== {stem} =====", flush=True)
        started = time.perf_counter()
        raw_lrc, source = _align_with_optional_demucs(
            str(audio_path),
            lyrics,
            device=device,
            enable_demucs_candidate=True,
        )
        prediction = parse_lrc_text(raw_lrc)
        metrics = evaluate(ground_truth, prediction)
        elapsed = round(time.perf_counter() - started, 1)
        errors = [
            abs(ground_truth[index][0] - prediction[index][0])
            for index in range(min(len(ground_truth), len(prediction)))
        ]
        all_errors.extend(errors)
        result = {
            "track": stem,
            "source": source,
            "seconds": elapsed,
            **metrics,
        }
        results.append(result)
        print(
            f"  source={source}; lines={metrics['pred_lines']}/{metrics['gt_lines']}; "
            f"mean={metrics['mean']}s p95={metrics['p95']}s max={metrics['max']}s "
            f"time={elapsed}s",
            flush=True,
        )

    report = {
        "pipeline": "AiSyncWorker._align_with_optional_demucs",
        "device": device,
        "demucs_candidate_enabled": True,
        "per_track": results,
        "global_positional": summarize(all_errors),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nGlobal positional: {report['global_positional']}")
    print(f"Report saved to {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
