"""Compare two AI sync benchmark JSON reports."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if __package__:
    from .metrics import compare_reports
else:  # Direct ``python tools/ai_sync_bench/compare_runs.py`` invocation.
    from tools.ai_sync_bench.metrics import compare_reports


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "summary" not in payload:
        raise ValueError(f"Not an AI benchmark report: {path}")
    return payload


def _render(comparison: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# AI Sync Benchmark Comparison",
            "",
            f"- baseline: `{(comparison.get('baseline') or {}).get('backend', 'unknown')}`",
            f"- candidate: `{(comparison.get('candidate') or {}).get('backend', 'unknown')}`",
            f"- median total delta: `{_format_ms(comparison.get('total_ms_delta_median'))}`",
            f"- total change: `{_format_percent(comparison.get('total_ms_change_percent'))}`",
            "",
            "## Stage median deltas",
            "",
            "| Stage | Candidate - baseline |",
            "| --- | ---: |",
            *[
                f"| `{name}` | {_format_ms(value)} |"
                for name, value in (comparison.get("stage_median_delta_ms") or {}).items()
            ],
            "",
            "## Counter median deltas",
            "",
            "| Counter | Candidate - baseline |",
            "| --- | ---: |",
            *[
                f"| `{name}` | {_format_number(value)} |"
                for name, value in (comparison.get("counter_median_delta") or {}).items()
            ],
            "",
        ]
    )


def _format_ms(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):,.2f} ms"


def _format_percent(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):+.2f}%"


def _format_number(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):+.3f}"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("baseline", type=Path)
    result.add_argument("candidate", type=Path)
    result.add_argument("--output", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    comparison = compare_reports(_load(args.baseline), _load(args.candidate))
    text = _render(comparison)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
        args.output.with_suffix(".md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
