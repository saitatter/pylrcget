from __future__ import annotations

import json
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:
    import resource
except ImportError:  # pragma: no cover - resource is not available on Windows.
    resource = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"


def add_src_to_path() -> None:
    """Make benchmark scripts runnable directly from the repository root."""
    src = str(SRC_ROOT)
    if src not in sys.path:
        sys.path.insert(0, src)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def median(values: Iterable[float]) -> float | None:
    items = [float(value) for value in values]
    return statistics.median(items) if items else None


def peak_rss_bytes() -> int | None:
    """Return the process peak resident set size when the platform exposes it."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class _ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = _ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            process = ctypes.windll.kernel32.GetCurrentProcess()
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(
                process,
                ctypes.byref(counters),
                counters.cb,
            )
            if ok:
                return int(counters.PeakWorkingSetSize)
        except (AttributeError, OSError, TypeError):
            return None
        return None

    if resource is None:
        return None
    try:
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (AttributeError, OSError, ValueError):
        return None
    # Linux reports KiB, macOS reports bytes.
    return value * 1024 if sys.platform != "darwin" else value


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def format_ms(value: float | None) -> str:
    return "n/a" if value is None else f"{float(value):,.1f} ms"


def format_int(value: int | float | None) -> str:
    return "n/a" if value is None else f"{int(value):,}"
