#!/usr/bin/env python3
"""Benchmark the bulk LRCLIB pipeline using deterministic fixture responses."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    from .benchmark_common import REPO_ROOT, add_src_to_path, peak_rss_bytes, utc_now_iso, write_json
except ImportError:  # Direct ``python tools/perf/benchmark_lrclib.py`` execution.
    from benchmark_common import REPO_ROOT, add_src_to_path, peak_rss_bytes, utc_now_iso, write_json


add_src_to_path()

from core.lrclib_client import Lyrics, NotFoundError  # noqa: E402
from core.models import FsTrack  # noqa: E402
from db.migrations import DB_FILENAME, initialize_database  # noqa: E402
from db.queries import add_tracks  # noqa: E402
from ui.workers.bulk_lyrics_download_worker import BulkLyricsDownloadWorker  # noqa: E402


@dataclass
class _FixtureStats:
    lock: threading.Lock = field(default_factory=threading.Lock)
    requests_total: int = 0
    get_requests: int = 0
    search_requests: int = 0
    not_found: int = 0
    failures: int = 0
    latencies_ms: list[float] = field(default_factory=list)

    def record(self, kind: str, elapsed_ms: float, *, status: str = "ok") -> None:
        with self.lock:
            self.requests_total += 1
            if kind == "get":
                self.get_requests += 1
            else:
                self.search_requests += 1
            if status == "404":
                self.not_found += 1
            elif status != "ok":
                self.failures += 1
            self.latencies_ms.append(elapsed_ms)


class _FixtureAPI:
    def __init__(self, _base_url: str, fixture: dict, stats: _FixtureStats) -> None:
        self.fixture = fixture
        self.stats = stats

    def get_lyrics(self, track_name: str, artist_name: str, album_name: str, duration: int, *, cached: bool = False):
        started = time.perf_counter()
        entry = self.fixture["get"].get(
            "\t".join((artist_name.casefold(), track_name.casefold(), album_name.casefold(), str(duration)))
        )
        if entry is None:
            self.stats.record("get", (time.perf_counter() - started) * 1000, status="404")
            raise NotFoundError(404, "Not Found")
        self.stats.record("get", (time.perf_counter() - started) * 1000)
        return Lyrics(**entry)

    def search_lyrics(self, *, query=None, track_name=None, artist_name=None, album_name=None):
        started = time.perf_counter()
        key = json.dumps(
            {
                "query": query,
                "track_name": track_name,
                "artist_name": artist_name,
                "album_name": album_name,
            },
            sort_keys=True,
        )
        entry = self.fixture.get("search", {}).get(key, [])
        self.stats.record("search", (time.perf_counter() - started) * 1000)
        return [SimpleNamespace(**item) for item in entry]


def _environment() -> dict[str, object]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    return {
        "commit_sha": commit,
        "python": sys.version,
        "platform": sys.platform,
        "os_name": os.name,
    }


def _make_fixture(track_count: int, duplicate_every: int) -> tuple[list[dict[str, object]], dict[str, object]]:
    tracks: list[dict[str, object]] = []
    get_responses: dict[str, dict[str, object]] = {}
    for index in range(track_count):
        group = index // max(1, duplicate_every)
        artist = f"Artist {group:04d}"
        title = f"Track {group:04d}"
        album = f"Album {group:04d}"
        duration = 180
        response = {
            "id": index + 1,
            "name": "",
            "track_name": title,
            "artist_name": artist,
            "album_name": album,
            "duration": duration,
            "instrumental": False,
            "plain_lyrics": f"plain lyrics for {title}",
            "synced_lyrics": f"[00:00.00]synced lyrics for {title}",
            "lang": "en",
            "isrc": None,
            "spotify_id": None,
            "release_date": None,
        }
        get_key = "\t".join((artist.casefold(), title.casefold(), album.casefold(), str(duration)))
        get_responses[get_key] = response
        tracks.append({"artist": artist, "title": title, "album": album, "duration": duration})
    return tracks, {"get": get_responses, "search": {}}


def _load_fixture(path: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload["tracks"]), dict(payload["fixture"])


def _run_sample(tracks: list[dict[str, object]], fixture: dict[str, object], workers: int = 4) -> dict[str, object]:
    stats = _FixtureStats()
    with tempfile.TemporaryDirectory(prefix="pylrcget-lrclib-db-") as database_dir:
        db = initialize_database(database_dir)
        add_tracks(
            db,
            [
                FsTrack(
                    file_path=str(Path(database_dir) / f"{index:05d}.wav"),
                    file_name=f"{index:05d}.wav",
                    title=str(track["title"]),
                    album=str(track.get("album", "")),
                    artist=str(track["artist"]),
                    album_artist=str(track["artist"]),
                    duration=float(track.get("duration") or 180),
                    txt_lyrics=None,
                    lrc_lyrics=None,
                    track_number=index + 1,
                )
                for index, track in enumerate(tracks)
            ],
        )
        track_ids = [int(row["id"]) for row in db.execute("SELECT id FROM tracks ORDER BY id").fetchall()]
        db.close()
        worker = BulkLyricsDownloadWorker(
            str(Path(database_dir) / DB_FILENAME),
            track_ids,
            "fixture://lrclib",
        )
        worker_count = min(max(1, workers), max(1, len(track_ids)))
        finished_stats: list[dict[str, object]] = []
        worker.finishedBatch.connect(lambda _ok, _message, payload: finished_stats.append(payload))
        started = time.perf_counter()
        with patch(
            "ui.workers.bulk_lyrics_download_worker.LrcLibAPI",
            side_effect=lambda base_url: _FixtureAPI(base_url, fixture, stats),
        ), patch("ui.workers.bulk_lyrics_download_worker.MAX_PARALLEL_DOWNLOAD_WORKERS", worker_count):
            worker.run()
        elapsed_ms = (time.perf_counter() - started) * 1000

    ordered = sorted(stats.latencies_ms)
    success = len(tracks) - stats.not_found - stats.failures
    worker_stats = finished_stats[-1] if finished_stats else {}
    unique_lookup_keys = int(worker_stats.get("unique_lookup_keys", 0))
    deduplicated_tracks = int(worker_stats.get("deduplicated_tracks", 0))
    return {
        "total_ms": round(elapsed_ms, 3),
        "tracks_requested": len(tracks),
        "jobs_generated": len(tracks),
        "unique_lookup_keys": unique_lookup_keys,
        "http_requests_total": stats.requests_total,
        "get_requests": stats.get_requests,
        "search_requests": stats.search_requests,
        "requests_per_track": round(stats.requests_total / len(tracks), 4) if tracks else 0.0,
        "deduplicated_lookups": deduplicated_tracks,
        "retries": 0,
        "429_responses": 0,
        "404_responses": stats.not_found,
        "other_http_failures": stats.failures,
        "p50_request_latency_ms": round(ordered[len(ordered) // 2], 3) if ordered else None,
        "p95_request_latency_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 3) if ordered else None,
        "match_success_count": success,
        "match_failure_count": len(tracks) - success,
        "pending_future_high_water_mark": int(worker_stats.get("pending_future_high_water_mark", 0)),
        "peak_rss_bytes": peak_rss_bytes(),
        "worker_count": worker_count,
    }


def _summarize(samples: list[dict[str, object]]) -> dict[str, object]:
    numeric_keys = sorted(
        key for key, value in samples[0].items() if isinstance(value, (int, float)) and not isinstance(value, bool)
    ) if samples else []
    return {
        key: round(statistics.median(float(sample[key]) for sample in samples if sample.get(key) is not None), 3)
        if any(sample.get(key) is not None for sample in samples)
        else None
        for key in numeric_keys
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--tracks", type=int, default=250)
    parser.add_argument("--duplicate-every", type=int, default=1, help="Tracks per equivalent lookup key")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/results/lrclib.json"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.tracks <= 0 or args.duplicate_every <= 0 or args.workers <= 0 or args.runs <= 0 or args.warmups < 0:
        parser.error("tracks, duplicate-every, workers, and runs must be positive; warmups cannot be negative")

    if args.fixture:
        tracks, fixture = _load_fixture(args.fixture)
    else:
        tracks, fixture = _make_fixture(args.tracks, args.duplicate_every)
    for _ in range(args.warmups):
        _run_sample(tracks, fixture, workers=args.workers)
    samples = [_run_sample(tracks, fixture, workers=args.workers) for _ in range(args.runs)]
    report = {
        "kind": "lrclib",
        "created_at": utc_now_iso(),
        "environment": _environment(),
        "fixture": str(args.fixture.resolve()) if args.fixture else "generated",
        "tracks": len(tracks),
        "duplicate_every": args.duplicate_every,
        "warmups": args.warmups,
        "runs": args.runs,
        "median": _summarize(samples),
        "samples": samples,
    }
    write_json(args.output, report)
    report_path = args.report or args.output.with_suffix(".md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    median_values = report["median"]
    report_path.write_text(
        "\n".join(
            [
                "# PyLrcGet LRCLIB benchmark",
                "",
                f"Fixture: `{report['fixture']}`; tracks: `{report['tracks']}`; runs: `{report['runs']}`.",
                "",
                "| Metric | Median |",
                "|---|---:|",
                *[f"| `{key}` | {median_values.get(key, 'n/a')} |" for key in (
                    "total_ms",
                    "http_requests_total",
                    "requests_per_track",
                    "unique_lookup_keys",
                    "deduplicated_lookups",
                    "pending_future_high_water_mark",
                    "p50_request_latency_ms",
                    "p95_request_latency_ms",
                    "match_success_count",
                    "peak_rss_bytes",
                )],
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
