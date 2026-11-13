"""Benchmark local AI against embedded LRC ground truth using read-only originals."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import statistics
import subprocess
import sys
import time
import unicodedata
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from mutagen import File

from tools.ai_sync_bench.metrics import percentile, summarize
from ui.workers.ai.ai_sync_service import PersistentAIRuntime

TIMESTAMP = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")


def lrc_lines(text: str) -> list[tuple[float, str]]:
    """Keep file order, so sorting cannot hide backward timestamps."""
    result = []
    for line in text.splitlines():
        matches = list(TIMESTAMP.finditer(line))
        if not matches:
            continue
        lyric = line[matches[-1].end():].strip()
        if lyric:
            result.extend((int(m[1]) * 60 + float(m[2]), lyric) for m in matches)
    return result


def normalized(text: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def quality(reference: str, actual: str, duration_s: float) -> dict:
    expected, received = lrc_lines(reference), lrc_lines(actual)
    available = defaultdict(deque)
    for index, (seconds, text) in enumerate(received):
        available[normalized(text)].append((index, seconds))
    paired = []
    for index, (seconds, text) in enumerate(expected):
        candidates = available[normalized(text)]
        if candidates:
            actual_index, predicted = candidates.popleft()
            paired.append((index, actual_index, seconds, predicted))
    offsets = [predicted - seconds for _, _, seconds, predicted in paired]
    errors = [abs(offset) for offset in offsets]
    times = [seconds for seconds, _ in received]
    outliers = sorted(paired, key=lambda row: abs(row[3] - row[2]), reverse=True)[:5]
    return {
        "reference_lines": len(expected), "output_lines": len(received), "matched_lines": len(paired),
        "coverage": len(paired) / len(expected) if expected else 1.0,
        "missing_lines": len(expected) - len(paired), "extra_or_changed_lines": len(received) - len(paired),
        "mean_error_s": statistics.fmean(errors) if errors else None,
        "median_error_s": statistics.median(errors) if errors else None,
        "p90_error_s": percentile(errors, .90), "p95_error_s": percentile(errors, .95),
        "max_error_s": max(errors) if errors else None,
        "median_signed_offset_s": statistics.median(offsets) if offsets else None,
        **{f"within_{threshold:g}s": sum(error <= threshold for error in errors) / len(expected) if expected else 1.0 for threshold in (.25, .5, 1, 2)},
        "backward_timestamps": sum(right < left for left, right in pairwise(times)),
        "duplicate_timestamps": sum(right == left for left, right in pairwise(times)),
        "outside_audio": sum(seconds < 0 or seconds > duration_s for seconds in times),
        "outliers": [{"line": index + 1, "output_line": actual_index + 1, "reference_s": seconds, "actual_s": predicted, "error_s": abs(predicted - seconds)} for index, actual_index, seconds, predicted in outliers],
    }


def fingerprint(path: Path) -> dict:
    stat = path.stat()
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    return {"sha256": digest, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def embedded_reference(path: Path) -> tuple[str, float]:
    audio = File(path)
    if audio is None or audio.tags is None:
        raise ValueError(f"No readable embedded tags: {path.name}")
    for key in audio.tags.keys():  # noqa: SIM118 - Vorbis tag iteration yields (key, value) pairs.
        if "lyric" not in str(key).casefold() and not str(key).startswith(("USLT", "SYLT")):
            continue
        values = audio.tags[key]
        values = values if isinstance(values, list) else [values]
        for value in values:
            text = getattr(value, "text", value)
            if isinstance(text, str) and lrc_lines(text):
                return text, float(audio.info.length)
    raise ValueError(f"No timestamped embedded LRC lyrics: {path.name}")


def validate_output_path(sources: list[Path], output_root: Path) -> None:
    resolved = output_root.resolve()
    if any(resolved.is_relative_to(source.resolve().parent) for source in sources):
        raise ValueError("Benchmark output must be outside every input audio directory")


def write_report(path: Path, report: dict) -> None:
    temporary = path.with_suffix(".pending.json")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def markdown_report(report: dict) -> str:
    def number(value, digits=2):
        return f"{value:.{digits}f}" if value is not None else "n/a"

    lines = ["# Embedded-ground-truth AI benchmark", "", f"Captured: {report['captured_at']}", "",
             "Cold includes process startup and model loading. Warm values summarize measured runs after warm-up.", "",
             "| Input | Device | Demucs | Cold s | Warm median s | Warm p95 s | RTF | Coverage | Median error s | P95 error s | Max error s | Within 1 s |",
             "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for item in report["configurations"]:
        successful = [run for run in item["runs"] if run["ok"]]
        if not successful:
            lines.append(f"| {item['input']} | {item['device']} | {item['demucs']} | failed | | | | | | | | |")
            continue
        summary = summarize(run["elapsed_s"] for run in successful)
        # Timing errors are per run; take the median of each run's metric.
        aggregate = {}
        for key in ("coverage", "median_error_s", "p95_error_s", "max_error_s", "within_1s"):
            values = [run["quality"][key] for run in successful if run["quality"][key] is not None]
            aggregate[key] = statistics.median(values) if values else None
        lines.append(f"| {item['input']} | {item['device']} | {item['demucs']} | {item['cold']['elapsed_s']:.2f} | {summary['median']:.2f} | {summary['p95']:.2f} | {summary['median'] / item['duration_s']:.3f} | {aggregate['coverage']:.0%} | {number(aggregate['median_error_s'])} | {number(aggregate['p95_error_s'])} | {number(aggregate['max_error_s'])} | {aggregate['within_1s']:.0%} |")
    lines += ["", "RTF is wall time / audio duration; lower is faster. Timing is matched by normalized lyric text and occurrence, not by sorted timestamp position.", "",
              "Per-run measurements, line-numbered timing outliers and original-file integrity checks are in the accompanying JSON report.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, action="append", required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--devices", nargs="+", choices=("cpu", "cuda", "auto"), default=["cpu", "cuda", "auto"])
    parser.add_argument("--demucs", nargs="+", choices=("off", "on"), default=["off"])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    if args.runs < 1 or args.warmups < 1:
        parser.error("At least one cold warm-up and one measured run are required")
    sources = [path.resolve(strict=True) for path in args.audio]
    validate_output_path(sources, args.output_root)
    work = args.output_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    work.mkdir(parents=True)
    probe = subprocess.check_output([str(args.runtime), "-c", "import torch,platform,json,importlib.metadata as m; print(json.dumps({'python':platform.python_version(),'torch':torch.__version__,'torch_threads':torch.get_num_threads(),'cuda':torch.cuda.is_available(),'gpu':torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,'whisperx':m.version('whisperx')}))"], text=True, encoding="utf-8")
    source_digest = hashlib.sha256()
    for path in sorted((ROOT / "src/ui/workers/ai").glob("*.py")):
        source_digest.update(path.name.encode())
        source_digest.update(path.read_bytes())
    report = {"schema_version": 1, "captured_at": datetime.now(UTC).isoformat(), "runtime": json.loads(probe), "ai_source_sha256": source_digest.hexdigest(), "warmups": args.warmups, "measured_runs": args.runs, "inputs": [], "configurations": []}
    try:
        for number, source in enumerate(sources, 1):
            original = fingerprint(source)
            copied = work / f"input-{number:02d}{source.suffix}"
            shutil.copyfile(source, copied)
            assert fingerprint(copied)["sha256"] == original["sha256"]
            reference, duration = embedded_reference(copied)
            lines = lrc_lines(reference)
            report["inputs"].append({"id": f"input-{number:02d}", "source": str(source), "fingerprint_before": original, "duration_s": duration, "reference_lines": len(lines)})
            for device in args.devices:
                for demucs in args.demucs:
                    entry = {"input": f"input-{number:02d}", "device": device, "demucs": demucs, "duration_s": duration, "runs": []}
                    report["configurations"].append(entry)
                    service = PersistentAIRuntime(args.runtime, ROOT / "src", device=device)
                    try:
                        for iteration in range(args.warmups + args.runs):
                            print(f"{entry['input']} {device} demucs={demucs} run={iteration + 1}/{args.warmups + args.runs}", flush=True)
                            started = time.monotonic()
                            progress = []
                            config = {"audio_path": str(copied), "plain_lyrics": "\n".join(text for _, text in lines), "device": device, "language": "en", "whisper_model": "base", "enable_demucs_candidate": demucs == "on", "enable_fuzzy": True, "fuzzy_threshold": 60}
                            try:
                                ok, message, output = service.run(config, on_progress=progress.append, is_cancelled=lambda started=started: time.monotonic() - started > args.timeout)
                                row = {"ok": ok, "message": message, "elapsed_s": time.monotonic() - started, "quality": quality(reference, output, duration), "progress": progress}
                            except (OSError, RuntimeError, ValueError) as exc:
                                row = {"ok": False, "error": str(exc), "elapsed_s": time.monotonic() - started}
                            if iteration == 0:
                                entry["cold"] = row
                            if iteration >= args.warmups:
                                entry["runs"].append(row)
                            write_report(work / "report.json", report)
                            print(f"  ok={row['ok']} elapsed={row['elapsed_s']:.2f}s", flush=True)
                    finally:
                        service.shutdown()
    finally:
        for item in report["inputs"]:
            item["fingerprint_after"] = fingerprint(Path(item["source"]))
            item["original_unchanged"] = item["fingerprint_before"] == item["fingerprint_after"]
        write_report(work / "report.json", report)
    (work / "report.md").write_text(markdown_report(report), encoding="utf-8")
    if not all(item["original_unchanged"] for item in report["inputs"]):
        raise RuntimeError("An original changed during the run; inspect the integrity report")
    print(work / "report.md", flush=True)
    if any(not run["ok"] for item in report["configurations"] for run in item["runs"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
