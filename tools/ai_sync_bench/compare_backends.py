"""Convenience alias for comparing baseline and candidate AI backends."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if __package__:
    from .compare_runs import main
else:  # Direct ``python tools/ai_sync_bench/compare_backends.py`` invocation.
    from tools.ai_sync_bench.compare_runs import main


if __name__ == "__main__":
    raise SystemExit(main())
