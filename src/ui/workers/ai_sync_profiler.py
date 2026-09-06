"""Low-overhead timing and resource counters for AI sync experiments.

The profiler is deliberately independent of Qt and of any optional AI
dependency.  Production code can attach one to a worker when tracing is
enabled, while the benchmark harness can use it with fixture backends.
"""
from __future__ import annotations

import ctypes
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any


AI_SYNC_STAGES = (
    "process_startup",
    "runtime_initialization",
    "backend_import",
    "model_load",
    "audio_decode_resample",
    "language_detection",
    "g2p",
    "audio_copy",
    "demucs",
    "asr",
    "fixed_window_retry",
    "forced_alignment",
    "per_chunk_alignment",
    "relaxed_vad_retry",
    "viterbi",
    "repeat_repair",
    "tail_rescue",
    "lrc_render",
    "english_checkpoint_load",
    "english_g2p",
    "english_audio_copy",
    "english_subprocess",
    "english_inference",
    "english_parse",
)


def peak_rss_bytes() -> int | None:
    """Return the current process peak RSS when the platform exposes it."""
    if sys.platform == "win32":
        try:
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
            return int(counters.PeakWorkingSetSize) if ok else None
        except (AttributeError, OSError, TypeError):
            return None

    try:
        import resource

        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (ImportError, AttributeError, OSError, ValueError):
        return None
    # Linux reports KiB; macOS reports bytes.
    return value * 1024 if sys.platform != "darwin" else value


def _default_resources() -> dict[str, int | None]:
    return {"peak_rss_bytes": peak_rss_bytes()}


class StageProfiler:
    """Accumulate stage timings and counters for one alignment operation.

    ``clock`` and ``cpu_clock`` are injectable to make timing behavior
    deterministic in unit tests.  Unknown stage names are accepted so that a
    later experiment can add a stage without changing this utility first.
    """

    def __init__(
        self,
        *,
        metadata: dict[str, Any] | None = None,
        clock: Callable[[], int] | None = None,
        cpu_clock: Callable[[], float] | None = None,
        resource_sampler: Callable[[], dict[str, int | None]] | None = None,
    ) -> None:
        self._clock = clock or time.perf_counter_ns
        self._cpu_clock = cpu_clock or time.process_time
        self._resource_sampler = resource_sampler or _default_resources
        self._started_ns = self._clock()
        self._finished_ns: int | None = None
        self._started_cpu = self._cpu_clock()
        self._finished_cpu: float | None = None
        self._durations_ms = {stage: 0.0 for stage in AI_SYNC_STAGES}
        self._counters: dict[str, int | float] = {}
        self._observations: dict[str, list[float]] = {}
        self._metadata = dict(metadata or {})
        self._resources: dict[str, int | None] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = self._clock()
        try:
            yield
        finally:
            elapsed_ms = (self._clock() - started) / 1_000_000
            self._durations_ms[name] = self._durations_ms.get(name, 0.0) + elapsed_ms

    def increment(self, name: str, value: int | float = 1) -> None:
        self._counters[name] = self._counters.get(name, 0) + value

    def observe(self, name: str, value: int | float) -> None:
        self._observations.setdefault(name, []).append(float(value))

    def set_metadata(self, name: str, value: Any) -> None:
        self._metadata[name] = value

    def finish(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot, finalizing the total timer."""
        if self._finished_ns is None:
            self._finished_ns = self._clock()
            self._finished_cpu = self._cpu_clock()
            self._resources = dict(self._resource_sampler())
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        finished_ns = self._finished_ns if self._finished_ns is not None else self._clock()
        finished_cpu = self._finished_cpu if self._finished_cpu is not None else self._cpu_clock()
        durations = dict(self._durations_ms)
        durations["total"] = (finished_ns - self._started_ns) / 1_000_000
        resources = self._resources or dict(self._resource_sampler())
        return {
            "schema_version": 1,
            "metadata": dict(self._metadata),
            "stage_timings_ms": durations,
            "counters": dict(self._counters),
            "observations": {name: list(values) for name, values in self._observations.items()},
            "resources": resources,
            "cpu_time_ms": max(0.0, (finished_cpu - self._started_cpu) * 1000),
        }


__all__ = ["AI_SYNC_STAGES", "StageProfiler", "peak_rss_bytes"]
