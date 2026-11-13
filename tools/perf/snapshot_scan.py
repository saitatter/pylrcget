#!/usr/bin/env python3
"""Dump the scanner's database result for a library as a comparable snapshot.

The library is only read. Two scans run against one temporary database: the
initial scan and an unchanged rescan. Each state is written as canonical JSON
so snapshots taken before and after a scanner change can be compared with
``compare_snapshots``; the rescan must also leave the initial state intact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

try:
    from .benchmark_common import add_src_to_path
except ImportError:  # Direct ``python tools/perf/snapshot_scan.py`` execution.
    from benchmark_common import add_src_to_path

add_src_to_path()

from db.migrations import DB_FILENAME, initialize_database  # noqa: E402
from ui.workers.library_scanner import LibraryScanner  # noqa: E402

SNAPSHOT_QUERY = """
SELECT t.file_path, t.file_name, t.title, t.title_lower, t.duration,
       t.lrc_lyrics, t.txt_lyrics, t.instrumental, t.track_number,
       t.modified_time, t.file_size, t.isrc, t.txt_lyrics_source, t.lrc_lyrics_source,
       ar.name AS artist, al.name AS album, al.album_artist_name AS album_artist,
       s.audio_mtime_ns, s.audio_size, s.sidecar_signature,
       s.embedded_txt_present, s.embedded_lrc_present,
       s.sidecar_txt_present, s.sidecar_lrc_present,
       s.embedded_txt_lyrics, s.embedded_lrc_lyrics, s.signature_version
FROM tracks t
LEFT JOIN artists ar ON ar.id = t.artist_id
LEFT JOIN albums al ON al.id = t.album_id
LEFT JOIN track_scan_state s ON s.track_id = t.id
ORDER BY t.file_path
"""


def read_snapshot(database_path: Path) -> list[dict[str, object]]:
    db = sqlite3.connect(database_path)
    db.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in db.execute(SNAPSHOT_QUERY)]
    finally:
        db.close()


def snapshot_digest(rows: list[dict[str, object]]) -> str:
    payload = json.dumps(rows, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compare_snapshots(before: list[dict[str, object]], after: list[dict[str, object]]) -> list[str]:
    """Return human-readable differences, keyed by file path."""
    differences: list[str] = []
    before_by_path = {str(row["file_path"]): row for row in before}
    after_by_path = {str(row["file_path"]): row for row in after}
    for path in sorted(before_by_path.keys() - after_by_path.keys()):
        differences.append(f"missing after: {path}")
    for path in sorted(after_by_path.keys() - before_by_path.keys()):
        differences.append(f"added after: {path}")
    for path in sorted(before_by_path.keys() & after_by_path.keys()):
        old, new = before_by_path[path], after_by_path[path]
        changed = sorted(key for key in old.keys() | new.keys() if old.get(key) != new.get(key))
        if changed:
            differences.append(f"changed {', '.join(changed)}: {path}")
    return differences


def _scan(database_path: Path, library: Path, workers: int) -> tuple[float, str]:
    messages: list[str] = []
    scanner = LibraryScanner(str(database_path), [str(library)], scan_worker_count=workers)
    scanner.finished_signal.connect(lambda _ok, message: messages.append(message))
    started = time.perf_counter()
    scanner.run()
    return time.perf_counter() - started, messages[-1] if messages else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare", type=Path, nargs=2, metavar=("BEFORE", "AFTER"))
    args = parser.parse_args()

    if args.compare:
        before, after = (json.loads(path.read_text(encoding="utf-8")) for path in args.compare)
        differences = compare_snapshots(before["rows"], after["rows"])
        for difference in differences[:50]:
            print(difference)
        print(f"{len(before['rows'])} rows before, {len(after['rows'])} rows after, {len(differences)} differences")
        return 1 if differences else 0

    if args.library is None or args.output is None:
        parser.error("--library and --output are required unless --compare is used")
    if not args.library.is_dir():
        parser.error(f"Library directory does not exist: {args.library}")

    with tempfile.TemporaryDirectory(prefix="pylrcget-scan-snapshot-") as database_dir:
        initialize_database(database_dir).close()
        database_path = Path(database_dir) / DB_FILENAME
        initial_s, initial_message = _scan(database_path, args.library, args.workers)
        rows = read_snapshot(database_path)
        unchanged_s, unchanged_message = _scan(database_path, args.library, args.workers)
        rescan_differences = compare_snapshots(rows, read_snapshot(database_path))

    report = {
        "library_root": str(args.library),
        "initial_s": round(initial_s, 3),
        "initial_message": initial_message,
        "unchanged_s": round(unchanged_s, 3),
        "unchanged_message": unchanged_message,
        "rescan_differences": rescan_differences,
        "digest": snapshot_digest(rows),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2))
    print(f"{len(rows)} rows written to {args.output}")
    return 1 if rescan_differences else 0


if __name__ == "__main__":
    sys.exit(main())
