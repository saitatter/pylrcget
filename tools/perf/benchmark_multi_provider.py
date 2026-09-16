#!/usr/bin/env python3
"""Benchmark the provider router with local deterministic fixtures only."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path

try:
    from .benchmark_common import (
        REPO_ROOT,
        add_src_to_path,
        peak_rss_bytes,
        utc_now_iso,
        write_json,
    )
except ImportError:  # Direct ``python tools/perf/benchmark_multi_provider.py`` execution.
    from benchmark_common import (
        REPO_ROOT,
        add_src_to_path,
        peak_rss_bytes,
        utc_now_iso,
        write_json,
    )


add_src_to_path()

from lyrics.providers import (
    LyricsProviderCapabilities,
    LyricsProviderResult,
    LyricsProviderRouter,
    ProviderHealthState,
    ProviderLookupResultCache,
    TrackLookupContext,
)

MAX_PENDING_MULTIPLIER = 4


@dataclass
class _ProviderStats:
    lock: threading.Lock = field(default_factory=threading.Lock)
    attempted: int = 0
    cache_hits: int = 0
    searches: int = 0
    direct_id_lookups: int = 0
    synced: int = 0
    plain: int = 0
    no_match: int = 0
    low_confidence: int = 0
    errors: int = 0
    rate_limits: int = 0
    latencies_ms: list[float] = field(default_factory=list)

    def record(self, *, method: str, result_type: str, elapsed_ms: float) -> None:
        with self.lock:
            self.attempted += 1
            if method == "direct_id":
                self.direct_id_lookups += 1
            else:
                self.searches += 1
            if result_type == "synced":
                self.synced += 1
            elif result_type == "plain":
                self.plain += 1
            elif result_type == "low_confidence":
                self.low_confidence += 1
            elif result_type == "error":
                self.errors += 1
            else:
                self.no_match += 1
            self.latencies_ms.append(elapsed_ms)


class _FixtureProvider:
    def __init__(self, provider_id: str, stats: _ProviderStats) -> None:
        self.provider_id = provider_id
        self.display_name = provider_id.title()
        self._stats = stats

    def capabilities(self) -> LyricsProviderCapabilities:
        return LyricsProviderCapabilities(True, True, True, True, False)

    def lookup(self, track, *, requested_mode, cancel_event=None):
        del requested_mode
        started_at = time.perf_counter()
        if cancel_event is not None and cancel_event.is_set():
            return None
        method = "direct_id" if track.isrc else "search"
        group_id = int(track.track_id or 0)
        if self.provider_id == "lrclib":
            result_type = "plain" if group_id % 5 == 0 else "synced"
            result = _result(
                self.provider_id,
                track,
                synced=None if result_type == "plain" else f"[00:01.00]{track.title}",
                plain=f"plain {track.title}" if result_type == "plain" else None,
                method=method,
            )
        elif self.provider_id == "tidal":
            result_type = "synced"
            result = _result(self.provider_id, track, synced=f"[00:01.00]{track.title}", plain=None, method=method)
        else:
            result_type = "no_match"
            result = None
        self._stats.record(
            method=method,
            result_type=result_type,
            elapsed_ms=(time.perf_counter() - started_at) * 1000,
        )
        return result


def _result(
    provider: str,
    track: TrackLookupContext,
    *,
    synced: str | None,
    plain: str | None,
    method: str,
) -> LyricsProviderResult:
    return LyricsProviderResult(
        provider=provider,
        provider_track_id=f"{provider}-{track.track_id}",
        plain_lyrics=plain,
        synced_lyrics=synced,
        instrumental=False,
        match_score=100.0,
        match_method=method,
        remote_title=track.title,
        remote_artist=track.artists[0] if track.artists else None,
        remote_album=track.album,
        remote_duration_seconds=track.duration_seconds,
        remote_isrc=track.isrc,
    )


def _contexts(track_count: int, duplicate_every: int) -> list[TrackLookupContext]:
    result: list[TrackLookupContext] = []
    for index in range(track_count):
        group = index // duplicate_every
        result.append(
            TrackLookupContext(
                track_id=index,
                file_path=f"fixture-{index}.wav",
                title=f"Track {group:04d}",
                artists=(f"Artist {group:04d}",),
                album=f"Album {group:04d}",
                album_artist=f"Artist {group:04d}",
                duration_seconds=180.0,
                track_number=1,
                isrc=f"USAAA{group:07d}" if group % 2 == 0 else None,
            )
        )
    return result


def _lookup_key(track: TrackLookupContext) -> tuple[str, str, str, str, str, int | None]:
    return (
        "router",
        str(track.isrc or "").casefold(),
        str(track.artists[0] if track.artists else "").casefold(),
        str(track.title or "").casefold(),
        str(track.album or "").casefold(),
        round(track.duration_seconds) if track.duration_seconds else None,
    )


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
    }


def run_benchmark(track_count: int, duplicate_every: int, workers: int) -> dict[str, object]:
    if track_count <= 0 or duplicate_every <= 0 or workers <= 0:
        raise ValueError("track_count, duplicate_every, and workers must be positive")
    contexts = _contexts(track_count, duplicate_every)
    groups: dict[tuple[str, str, str, str, str, int | None], list[TrackLookupContext]] = {}
    for context in contexts:
        groups.setdefault(_lookup_key(context), []).append(context)

    stats_by_provider = {provider_id: _ProviderStats() for provider_id in ("lrclib", "tidal")}
    providers = tuple(_FixtureProvider(provider_id, stats_by_provider[provider_id]) for provider_id in stats_by_provider)
    router = LyricsProviderRouter(providers)
    health = ProviderHealthState()
    result_cache = ProviderLookupResultCache()
    pending_high_water = 0
    completed = 0
    successful = 0
    started_at = time.perf_counter()
    executor = ThreadPoolExecutor(max_workers=min(workers, max(1, len(groups))))
    pending = {}
    group_items = list(groups.items())
    next_index = 0
    max_pending = workers * MAX_PENDING_MULTIPLIER

    def submit_available() -> None:
        nonlocal next_index, pending_high_water
        while next_index < len(group_items) and len(pending) < max_pending:
            key, members = group_items[next_index]
            next_index += 1
            representative = members[0]

            def fetch(context=representative, lookup_key=key):
                cache_hit, cached = result_cache.get(lookup_key)
                if cache_hit:
                    return cached
                result = router.lookup(context, requested_mode="prefer_synced", health_state=health)
                result_cache.put(lookup_key, result)
                return result

            pending[executor.submit(fetch)] = members
            pending_high_water = max(pending_high_water, len(pending))

    try:
        submit_available()
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                members = pending.pop(future)
                result = future.result()
                completed += len(members)
                if result is not None:
                    successful += len(members)
            submit_available()
    finally:
        executor.shutdown(wait=True)

    elapsed_ms = (time.perf_counter() - started_at) * 1000
    provider_report: dict[str, dict[str, object]] = {}
    for provider_id, provider_stats in stats_by_provider.items():
        latencies = sorted(provider_stats.latencies_ms)
        provider_report[provider_id] = {
            "attempted": provider_stats.attempted,
            "cache_hits": provider_stats.cache_hits,
            "searches": provider_stats.searches,
            "direct_id_lookups": provider_stats.direct_id_lookups,
            "synced": provider_stats.synced,
            "plain": provider_stats.plain,
            "no_match": provider_stats.no_match,
            "low_confidence": provider_stats.low_confidence,
            "errors": provider_stats.errors,
            "429": provider_stats.rate_limits,
            "p50_request_latency_ms": _percentile(latencies, 0.50),
            "p95_request_latency_ms": _percentile(latencies, 0.95),
        }
    return {
        "total_ms": round(elapsed_ms, 3),
        "tracks_processed": completed,
        "unique_lookup_keys": len(groups),
        "duplicates_avoided": len(contexts) - len(groups),
        "requests_saved": len(contexts) - sum(report["attempted"] for report in provider_report.values()),
        "successful_matches": successful,
        "match_failures": len(contexts) - successful,
        "pending_future_high_water_mark": pending_high_water,
        "peak_rss_bytes": peak_rss_bytes(),
        "worker_count": workers,
        "providers": provider_report,
        "provider_health": health.snapshot(),
        "result_cache_hits": result_cache.hits,
    }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    index = min(len(values) - 1, round((len(values) - 1) * fraction))
    return round(values[index], 3)


def _median_samples(samples: list[dict[str, object]]) -> dict[str, object]:
    keys = (
        "total_ms",
        "tracks_processed",
        "unique_lookup_keys",
        "duplicates_avoided",
        "requests_saved",
        "successful_matches",
        "match_failures",
        "pending_future_high_water_mark",
        "peak_rss_bytes",
        "result_cache_hits",
    )
    return {
        key: round(statistics.median(float(sample[key]) for sample in samples), 3)
        for key in keys
        if samples and sample_value_is_numeric(samples[0].get(key))
    }


def sample_value_is_numeric(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracks", type=int, default=250)
    parser.add_argument("--duplicate-every", type=int, default=5)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/results/multi-provider.json"))
    args = parser.parse_args()
    if args.warmups < 0 or args.runs <= 0:
        parser.error("runs must be positive; warmups cannot be negative")
    for _ in range(args.warmups):
        run_benchmark(args.tracks, args.duplicate_every, args.workers)
    samples = [run_benchmark(args.tracks, args.duplicate_every, args.workers) for _ in range(args.runs)]
    report = {
        "kind": "multi-provider",
        "created_at": utc_now_iso(),
        "environment": _environment(),
        "tracks": args.tracks,
        "duplicate_every": args.duplicate_every,
        "workers": args.workers,
        "warmups": args.warmups,
        "runs": args.runs,
        "median": _median_samples(samples),
        "providers": samples[-1]["providers"] if samples else {},
        "samples": samples,
    }
    write_json(args.output, report)
    report_path = args.output.with_suffix(".md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    median = report["median"]
    report_path.write_text(
        "\n".join(
            [
                "# PyLrcGet multi-provider benchmark",
                "",
                f"Tracks: `{args.tracks}`; duplicate every: `{args.duplicate_every}`; runs: `{args.runs}`.",
                "",
                "| Metric | Median |",
                "|---|---:|",
                *[f"| `{key}` | {median.get(key, 'n/a')} |" for key in median],
                "",
                "## Providers",
                "",
                "| Provider | Attempted | Direct ID | Search | Synced | Plain | No match | p50 ms | p95 ms |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
                *[
                    "| {provider} | {attempted} | {direct_id_lookups} | {searches} | {synced} | {plain} | "
                    "{no_match} | {p50_request_latency_ms} | {p95_request_latency_ms} |".format(
                        provider=provider,
                        **values,
                    )
                    for provider, values in report["providers"].items()
                ],
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(report["median"], indent=2))
    print(f"JSON report: {args.output}")
    print(f"Markdown report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
