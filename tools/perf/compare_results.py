#!/usr/bin/env python3
"""Compare two JSON benchmark reports and print a compact Markdown summary."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _median(report: dict, key: str) -> float | None:
    value = report.get("median", {}).get(key)
    return float(value) if value is not None else None


def compare(baseline_path: Path, candidate_path: Path) -> str:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    keys = sorted(set(baseline.get("median", {})) & set(candidate.get("median", {})))
    lines = [
        f"# Benchmark comparison: `{baseline_path.name}` vs `{candidate_path.name}`",
        "",
        "| Metric | Baseline | Candidate | Delta |",
        "|---|---:|---:|---:|",
    ]
    for key in keys:
        left = _median(baseline, key)
        right = _median(candidate, key)
        if left is None or right is None:
            continue
        delta = right - left
        lines.append(f"| `{key}` | {left:,.3f} | {right:,.3f} | {delta:+,.3f} |")
    lines.extend(
        [
            "",
            f"Baseline commit: `{baseline.get('environment', {}).get('commit_sha', 'unknown')}`",
            f"Candidate commit: `{candidate.get('environment', {}).get('commit_sha', 'unknown')}`",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = compare(args.baseline, args.candidate)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
