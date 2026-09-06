#!/usr/bin/env python3
"""Compare scanner worker counts on the same deterministic corpus."""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

try:
    from .benchmark_common import utc_now_iso, write_json
    from .benchmark_scan import _one_sample
except ImportError:  # Direct ``python tools/perf/benchmark_worker_sweep.py`` execution.
    from benchmark_common import utc_now_iso, write_json
    from benchmark_scan import _one_sample


def _parse_workers(value: str) -> list[int]:
    workers = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not workers or any(worker <= 0 for worker in workers):
        raise argparse.ArgumentTypeError("workers must be a comma-separated list of positive integers")
    return list(dict.fromkeys(workers))


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--workers", type=_parse_workers, default=[1, 2, 4, 8])
    parser.add_argument("--scenario", choices=("initial", "unchanged", "audio-changed", "sidecar-added", "sidecar-changed", "sidecar-removed", "sidecar-renamed", "mixed"), default="initial")
    parser.add_argument("--fraction", type=float, default=0.01)
    parser.add_argument("--suffix", choices=(".lrc", ".txt"), default=".lrc")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/results/scan-worker-sweep.json"))
    args = parser.parse_args()
    if args.warmups < 0 or args.runs <= 0:
        parser.error("runs must be positive; warmups cannot be negative")
    if not args.library.is_dir():
        parser.error(f"Library directory does not exist: {args.library}")

    results: dict[str, dict[str, object]] = {}
    for worker_count in args.workers:
        for index in range(args.warmups):
            _one_sample(
                args.library,
                scenario=args.scenario,
                worker_count=worker_count,
                fraction=args.fraction,
                suffix=args.suffix,
                seed=args.seed + index,
            )
        samples = [
            _one_sample(
                args.library,
                scenario=args.scenario,
                worker_count=worker_count,
                fraction=args.fraction,
                suffix=args.suffix,
                seed=args.seed + args.warmups + index,
            )
            for index in range(args.runs)
        ]
        results[str(worker_count)] = {
            "worker_count": worker_count,
            "median": _summarize(samples),
            "samples": samples,
        }

    report = {
        "kind": "scan-worker-sweep",
        "created_at": utc_now_iso(),
        "library_root": str(args.library.resolve()),
        "scenario": args.scenario,
        "fraction": args.fraction,
        "suffix": args.suffix,
        "workers": args.workers,
        "warmups": args.warmups,
        "runs": args.runs,
        "results": results,
    }
    write_json(args.output, report)
    report_path = args.output.with_suffix(".md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# PyLrcGet scanner worker sweep",
        "",
        f"Scenario: `{args.scenario}`; runs: `{args.runs}`; warmups: `{args.warmups}`.",
        "",
        "| Workers | Total ms | Tracks/sec | Mutagen calls | Peak RSS bytes |",
        "|---:|---:|---:|---:|---:|",
    ]
    for worker_count in args.workers:
        median = results[str(worker_count)]["median"]
        lines.append(
            f"| {worker_count} | {median.get('total_ms', 'n/a')} | {median.get('tracks_per_second', 'n/a')} | "
            f"{median.get('mutagen_file_calls', 'n/a')} | {median.get('peak_rss_bytes', 'n/a')} |"
        )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({worker: value["median"] for worker, value in results.items()}, indent=2))
    print(f"JSON report: {args.output}")
    print(f"Markdown report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
