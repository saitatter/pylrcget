#!/usr/bin/env python3
"""Benchmark the existing PyLrcGet scanner against a local audio corpus."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import os
import re
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

try:
    from .benchmark_common import REPO_ROOT, add_src_to_path, peak_rss_bytes, utc_now_iso, write_json
    from .mutate_test_library import mutate
except ImportError:  # Direct ``python tools/perf/benchmark_scan.py`` execution.
    from benchmark_common import REPO_ROOT, add_src_to_path, peak_rss_bytes, utc_now_iso, write_json
    from mutate_test_library import mutate


add_src_to_path()

from db.migrations import DB_FILENAME  # noqa: E402
from db.migrations import initialize_database  # noqa: E402
from library import scan_library  # noqa: E402
from ui.workers import library_scanner  # noqa: E402


SUMMARY_RE = re.compile(
    r"Library scan summary: (\d+) discovered, (\d+) scanned, (\d+) unchanged, "
    r"(\d+) updated, (\d+) removed, (\d+) worker failures"
)
TIMING_PATTERNS = {
    "enumeration_ms": re.compile(r"path discovery cumulative worker time: ([0-9.]+)s"),
    "audio_fast_path_ms": re.compile(r"audio-only fast path cumulative worker time: ([0-9.]+)s"),
    "signature_check_ms": re.compile(r"signature check cumulative worker time: ([0-9.]+)s"),
    "signature_audio_stat_ms": re.compile(r"signature audio stat cumulative worker time: ([0-9.]+)s"),
    "signature_sidecar_stat_ms": re.compile(r"signature sidecar stat cumulative worker time: ([0-9.]+)s"),
    "metadata_parse_ms": re.compile(r"metadata read cumulative worker time: ([0-9.]+)s"),
    "embedded_lyrics_ms": re.compile(r"embedded lyrics read cumulative worker time: ([0-9.]+)s"),
    "sidecar_lookup_ms": re.compile(r"sidecar lookup cumulative worker time: ([0-9.]+)s"),
    "db_write_ms": re.compile(r"DB flush cumulative worker time: ([0-9.]+)s"),
}


class _LogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class _Instrumentation:
    def __init__(self) -> None:
        self.mutagen_calls = 0
        self.metadata_reads = 0
        self.embedded_lyrics_reads = 0
        self.sidecar_reads = 0
        self.sidecar_directory_scans = 0
        self.scandir_calls = 0
        self.listdir_calls = 0
        self.stat_calls = 0
        self.sql_reads = 0
        self.sql_writes = 0
        self.insert_count = 0
        self.update_count = 0
        self.delete_count = 0

    def sql_trace(self, statement: str) -> None:
        normalized = statement.lstrip().upper()
        if normalized.startswith("SELECT") or normalized.startswith("PRAGMA"):
            self.sql_reads += 1
        if normalized.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")):
            self.sql_writes += 1
        if normalized.startswith("INSERT"):
            self.insert_count += 1
        elif normalized.startswith("UPDATE"):
            self.update_count += 1
        elif normalized.startswith("DELETE"):
            self.delete_count += 1


def _environment() -> dict[str, object]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    return {
        "commit_sha": commit,
        "python": sys.version,
        "platform": sys.platform,
        "os_name": os.name,
        "cwd": str(Path.cwd()),
    }


def _parse_log_metrics(messages: list[str]) -> dict[str, object]:
    result: dict[str, object] = {}
    for message in messages:
        summary = SUMMARY_RE.search(message)
        if summary:
            names = ("files_discovered", "files_scanned", "unchanged", "updated", "removed", "worker_failures")
            result.update({name: int(value) for name, value in zip(names, summary.groups(), strict=True)})
        for key, pattern in TIMING_PATTERNS.items():
            match = pattern.search(message)
            if match:
                result[key] = round(float(match.group(1)) * 1000, 3)
        if "signature sidecar stat cumulative worker time" in message:
            candidate_match = re.search(r"\((\d+) candidates\)", message)
            if candidate_match:
                result["sidecar_candidate_checks"] = int(candidate_match.group(1))
        if "audio-only fast path cumulative worker time" in message:
            fast_match = re.search(r"\((\d+) attempts, (\d+) hits\)", message)
            if fast_match:
                result["audio_fast_path_attempts"] = int(fast_match.group(1))
                result["audio_fast_path_hits"] = int(fast_match.group(2))
    return result


def _run_scan(
    library_root: Path,
    *,
    worker_count: int,
    instrumentation: _Instrumentation,
    database_dir: Path | None = None,
    instrumentation_enabled: bool = True,
) -> dict[str, object]:
    log_capture = _LogCapture()
    logger = logging.getLogger("ui.workers.library_scanner")
    previous_level = logger.level
    logger.setLevel(logging.DEBUG if instrumentation_enabled else logging.INFO)
    logger.addHandler(log_capture)

    original_connect = sqlite3.connect
    original_mutagen_file = scan_library.MutagenFile
    original_metadata_read = library_scanner.read_audio_metadata_for_scan
    original_embedded_read = scan_library.read_embedded_lyrics_from_audio
    original_sidecar_read = scan_library._read_sidecar
    original_sidecar_resolve_entry = scan_library.SidecarLookupCache.resolve_entry
    original_scandir = scan_library.os.scandir
    original_listdir = scan_library.os.listdir
    original_stat = scan_library.os.stat

    def counted_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(instrumentation.sql_trace)
        return connection

    def counted_mutagen_file(*args, **kwargs):
        instrumentation.mutagen_calls += 1
        return original_mutagen_file(*args, **kwargs)

    def counted_metadata_read(*args, **kwargs):
        instrumentation.metadata_reads += 1
        return original_metadata_read(*args, **kwargs)

    def counted_embedded_read(*args, **kwargs):
        instrumentation.embedded_lyrics_reads += 1
        return original_embedded_read(*args, **kwargs)

    def counted_sidecar_read(*args, **kwargs):
        instrumentation.sidecar_reads += 1
        return original_sidecar_read(*args, **kwargs)

    def counted_scandir(*args, **kwargs):
        instrumentation.scandir_calls += 1
        return original_scandir(*args, **kwargs)

    def counted_sidecar_resolve_entry(cache, candidate):
        before = len(cache._dir_entries)
        result = original_sidecar_resolve_entry(cache, candidate)
        instrumentation.sidecar_directory_scans += max(0, len(cache._dir_entries) - before)
        return result

    def counted_listdir(*args, **kwargs):
        instrumentation.listdir_calls += 1
        return original_listdir(*args, **kwargs)

    def counted_stat(*args, **kwargs):
        instrumentation.stat_calls += 1
        return original_stat(*args, **kwargs)

    database_context = (
        tempfile.TemporaryDirectory(prefix="pylrcget-scan-db-")
        if database_dir is None
        else contextlib.nullcontext(str(database_dir))
    )
    with database_context as database_dir_value:
        database_path = Path(database_dir_value) / DB_FILENAME
        db = initialize_database(database_dir_value)
        db.close()

        started = time.perf_counter()
        cpu_started = time.process_time()
        try:
            with contextlib.ExitStack() as instrumentation_stack:
                if instrumentation_enabled:
                    instrumentation_stack.enter_context(
                        patch.object(scan_library, "MutagenFile", side_effect=counted_mutagen_file)
                    )
                    instrumentation_stack.enter_context(
                        patch.object(library_scanner, "read_audio_metadata_for_scan", side_effect=counted_metadata_read)
                    )
                    instrumentation_stack.enter_context(
                        patch.object(scan_library, "read_embedded_lyrics_from_audio", side_effect=counted_embedded_read)
                    )
                    instrumentation_stack.enter_context(
                        patch.object(scan_library, "_read_sidecar", side_effect=counted_sidecar_read)
                    )
                    instrumentation_stack.enter_context(
                        patch.object(scan_library.SidecarLookupCache, "resolve_entry", new=counted_sidecar_resolve_entry)
                    )
                    instrumentation_stack.enter_context(
                        patch.object(scan_library.os, "scandir", side_effect=counted_scandir)
                    )
                    instrumentation_stack.enter_context(
                        patch.object(scan_library.os, "listdir", side_effect=counted_listdir)
                    )
                    instrumentation_stack.enter_context(
                        patch.object(scan_library.os, "stat", side_effect=counted_stat)
                    )
                    instrumentation_stack.enter_context(
                        patch.object(library_scanner.sqlite3, "connect", side_effect=counted_connect)
                    )
                scanner = library_scanner.LibraryScanner(
                    str(database_path),
                    [str(library_root)],
                    scan_worker_count=worker_count,
                )
                scanner.run()
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            cpu_ms = (time.process_time() - cpu_started) * 1000
            logger.removeHandler(log_capture)
            logger.setLevel(previous_level)

    result = _parse_log_metrics(log_capture.messages)
    result.update(
        {
            "total_ms": round(elapsed_ms, 3),
            "cpu_ms": round(cpu_ms, 3),
            "tracks_per_second": round((result.get("files_scanned", 0) / (elapsed_ms / 1000)), 3)
            if elapsed_ms > 0
            else 0.0,
            "audio_files_opened": instrumentation.mutagen_calls if instrumentation_enabled else None,
            "mutagen_file_calls": instrumentation.mutagen_calls if instrumentation_enabled else None,
            "metadata_extraction_count": instrumentation.metadata_reads if instrumentation_enabled else None,
            "embedded_lyrics_parse_count": instrumentation.embedded_lyrics_reads if instrumentation_enabled else None,
            "sidecar_lookup_count": instrumentation.sidecar_reads if instrumentation_enabled else None,
            "sidecar_directory_scans": instrumentation.sidecar_directory_scans if instrumentation_enabled else None,
            "scandir_calls": instrumentation.scandir_calls if instrumentation_enabled else None,
            "stat_calls": instrumentation.stat_calls if instrumentation_enabled else None,
            "db_read_count": instrumentation.sql_reads if instrumentation_enabled else None,
            "db_write_count": instrumentation.sql_writes if instrumentation_enabled else None,
            "insert_count": instrumentation.insert_count if instrumentation_enabled else None,
            "update_count": instrumentation.update_count if instrumentation_enabled else None,
            "delete_count": instrumentation.delete_count if instrumentation_enabled else None,
            "worker_count": worker_count,
            "instrumentation_enabled": instrumentation_enabled,
            "peak_rss_bytes": peak_rss_bytes(),
            "timing": {
                key: result.get(key)
                for key in (
                    "enumeration_ms",
                    "signature_check_ms",
                    "metadata_parse_ms",
                    "embedded_lyrics_ms",
                    "sidecar_lookup_ms",
                    "db_write_ms",
                    "total_ms",
                )
            },
        }
    )
    return result


def _prepare_mutation(library_root: Path, scenario: str, fraction: float, suffix: str, seed: int) -> None:
    if scenario == "unchanged":
        return
    if scenario == "initial":
        raise ValueError("initial does not have a mutation")
    operation = {
        "audio-changed": "change-audio",
        "sidecar-added": "add-sidecar",
        "sidecar-changed": "change-sidecar",
        "sidecar-removed": "remove-sidecar",
        "sidecar-renamed": "rename-sidecar",
        "mixed": "mixed",
    }.get(scenario)
    if operation is None:
        raise ValueError(f"Unsupported scenario: {scenario}")
    mutate(library_root, operation=operation, suffix=suffix, fraction=fraction, seed=seed)


def _one_sample(
    library_root: Path,
    *,
    scenario: str,
    worker_count: int,
    fraction: float,
    suffix: str,
    seed: int,
    read_only_source: bool = False,
    instrumentation_enabled: bool = True,
) -> dict[str, object]:
    if read_only_source and scenario not in {"initial", "unchanged"}:
        raise ValueError("read-only source mode supports only initial and unchanged scenarios")
    library_context = (
        contextlib.nullcontext(library_root)
        if read_only_source
        else tempfile.TemporaryDirectory(prefix="pylrcget-scan-corpus-")
    )
    with library_context as sample_root_value:
        sample_root = Path(sample_root_value)
        if not read_only_source:
            shutil.copytree(library_root, sample_root / "library")
            sample_root = sample_root / "library"
        with tempfile.TemporaryDirectory(prefix="pylrcget-scan-db-") as database_dir:
            database_path = Path(database_dir)
            if scenario == "initial":
                instrumentation = _Instrumentation()
                return _run_scan(
                    sample_root,
                    worker_count=worker_count,
                    instrumentation=instrumentation,
                    database_dir=database_path,
                    instrumentation_enabled=instrumentation_enabled,
                )

            # Seed sidecar state before the warmup when the measured operation is a
            # change, removal, or rename. The source corpus is copied per sample so
            # measured runs remain independent and never mutate the user's library.
            if scenario in {"sidecar-changed", "sidecar-removed", "sidecar-renamed"}:
                mutate(sample_root, operation="add-sidecar", suffix=suffix, fraction=fraction, seed=seed)
            warmup_instrumentation = _Instrumentation()
            _run_scan(
                sample_root,
                worker_count=worker_count,
                instrumentation=warmup_instrumentation,
                database_dir=database_path,
                instrumentation_enabled=instrumentation_enabled,
            )
            _prepare_mutation(sample_root, scenario, fraction, suffix, seed)
            instrumentation = _Instrumentation()
            return _run_scan(
                sample_root,
                worker_count=worker_count,
                instrumentation=instrumentation,
                database_dir=database_path,
                instrumentation_enabled=instrumentation_enabled,
            )


def _summarize(samples: list[dict[str, object]]) -> dict[str, object]:
    numeric_keys = sorted(
        key
        for key, value in samples[0].items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ) if samples else []
    return {
        key: round(statistics.median(float(sample[key]) for sample in samples if sample.get(key) is not None), 3)
        if any(sample.get(key) is not None for sample in samples)
        else None
        for key in numeric_keys
    }


def _markdown_report(report: dict[str, object]) -> str:
    median_values = report.get("median", {})
    lines = [
        "# PyLrcGet scan benchmark",
        "",
        f"Scenario: `{report['scenario']}`; runs: `{report['runs']}`; warmups: `{report['warmups']}`.",
        f"Library: `{report['library_root']}`; worker count: `{report['worker_count']}`.",
        "",
        "| Metric | Median |",
        "|---|---:|",
    ]
    for key in (
        "total_ms",
        "tracks_per_second",
        "files_discovered",
        "unchanged",
        "audio_files_opened",
        "mutagen_file_calls",
        "sidecar_directory_scans",
        "sidecar_candidate_checks",
        "metadata_extraction_count",
        "db_write_ms",
        "peak_rss_bytes",
    ):
        value = median_values.get(key)
        lines.append(f"| `{key}` | {value if value is not None else 'n/a'} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument(
        "--scenario",
        choices=("initial", "unchanged", "audio-changed", "sidecar-added", "sidecar-changed", "sidecar-removed", "sidecar-renamed", "mixed"),
        default="initial",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--fraction", type=float, default=0.01)
    parser.add_argument("--suffix", choices=(".lrc", ".txt"), default=".lrc")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--read-only-source",
        action="store_true",
        help="scan the source path directly; only initial and unchanged scenarios are supported",
    )
    parser.add_argument(
        "--lightweight",
        action="store_true",
        help="disable per-call instrumentation for accurate wall-clock timing",
    )
    parser.add_argument("--output", type=Path, default=Path("benchmarks/results/scan.json"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.workers <= 0 or args.warmups < 0 or args.runs <= 0:
        parser.error("workers and runs must be positive; warmups cannot be negative")
    if not args.library.is_dir():
        parser.error(f"Library directory does not exist: {args.library}")
    if args.read_only_source and args.scenario not in {"initial", "unchanged"}:
        parser.error("--read-only-source supports only initial and unchanged scenarios")

    for _ in range(args.warmups):
        with contextlib.redirect_stdout(io.StringIO()):
            _one_sample(
                args.library,
                scenario=args.scenario,
                worker_count=args.workers,
                fraction=args.fraction,
                suffix=args.suffix,
                seed=args.seed,
                read_only_source=args.read_only_source,
                instrumentation_enabled=not args.lightweight,
            )

    samples = [
        _one_sample(
            args.library,
            scenario=args.scenario,
            worker_count=args.workers,
            fraction=args.fraction,
            suffix=args.suffix,
            seed=args.seed + index,
            read_only_source=args.read_only_source,
            instrumentation_enabled=not args.lightweight,
        )
        for index in range(args.runs)
    ]
    report = {
        "kind": "scan",
        "created_at": utc_now_iso(),
        "environment": _environment(),
        "library_root": str(args.library.resolve()),
        "scenario": args.scenario,
        "worker_count": args.workers,
        "fraction": args.fraction,
        "suffix": args.suffix,
        "warmups": args.warmups,
        "runs": args.runs,
        "median": _summarize(samples),
        "samples": samples,
    }
    write_json(args.output, report)
    report_path = args.report or args.output.with_suffix(".md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_markdown_report(report) + "\n", encoding="utf-8")
    print(json.dumps(report["median"], indent=2))
    print(f"JSON report: {args.output}")
    print(f"Markdown report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
