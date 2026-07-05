# ui/library_scanner.py (or wherever LibraryScanner is defined)
import dataclasses
import logging
import os
import sqlite3
import time
import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from PySide6.QtCore import QThread, Signal

from core.utils import prepare_input
from library.scan_library import (
    get_audio_file_signature,
    iter_audio_paths,
    new_fs_track_from_path,
    SidecarLookupCache,
    read_audio_metadata,
)
from db.database import (
    add_tracks,
    delete_tracks_by_paths,
    get_library_scan_index,
    get_orphan_lyrics_index,
    prune_library,
)


logger = logging.getLogger(__name__)
LIBRARY_SCAN_MAX_WORKERS = 4
LIBRARY_SCAN_MAX_PENDING_MULTIPLIER = 4


class _ScanTimingStats:
    def __init__(self) -> None:
        self.path_discovery_s = 0.0
        self.audio_fast_path_s = 0.0
        self.signature_check_s = 0.0
        self.signature_audio_stat_s = 0.0
        self.signature_sidecar_stat_s = 0.0
        self.metadata_read_s = 0.0
        self.embedded_lyrics_read_s = 0.0
        self.sidecar_lookup_s = 0.0
        self.db_flush_s = 0.0
        self.path_discovery_count = 0
        self.audio_fast_path_count = 0
        self.audio_fast_path_hit_count = 0
        self.signature_check_count = 0
        self.signature_sidecar_candidate_count = 0
        self.metadata_read_count = 0
        self.embedded_lyrics_read_count = 0
        self.sidecar_lookup_count = 0
        self.db_flush_count = 0
        self._lock = threading.Lock()

    def record(self, field_name: str, elapsed_s: float) -> None:
        if elapsed_s <= 0:
            return
        with self._lock:
            current = getattr(self, field_name)
            setattr(self, field_name, current + elapsed_s)
            if field_name == "path_discovery_s":
                self.path_discovery_count += 1
            elif field_name == "audio_fast_path_s":
                self.audio_fast_path_count += 1
            elif field_name == "audio_fast_path_hit_count":
                self.audio_fast_path_hit_count += int(elapsed_s)
            elif field_name == "signature_check_s":
                self.signature_check_count += 1
            elif field_name == "signature_sidecar_candidate_count":
                self.signature_sidecar_candidate_count += int(elapsed_s)
            elif field_name == "metadata_read_s":
                self.metadata_read_count += 1
            elif field_name == "embedded_lyrics_read_s":
                self.embedded_lyrics_read_count += 1
            elif field_name == "sidecar_lookup_s":
                self.sidecar_lookup_count += 1
            elif field_name == "db_flush_s":
                self.db_flush_count += 1


@dataclass(frozen=True)
class _ScanTaskResult:
    path: str
    replace_existing: bool
    track: object | None


def _read_metadata_for_scan(path: str, *, timings: _ScanTimingStats | None = None):
    started_at = time.perf_counter()
    try:
        return read_audio_metadata(path)
    except Exception as exc:
        logger.warning("Skipping unreadable audio file during scan: %s (%s)", path, exc)
        return None
    finally:
        if timings is not None:
            timings.record("metadata_read_s", time.perf_counter() - started_at)


def _scan_worker_count() -> int:
    cpu_count = os.cpu_count() or LIBRARY_SCAN_MAX_WORKERS
    return max(1, min(LIBRARY_SCAN_MAX_WORKERS, cpu_count))


def _scan_track_for_path(
    path: str,
    *,
    replace_existing: bool,
    lyrics_lookup_subdir: str,
    lyrics_file_pattern: str,
    timings: _ScanTimingStats | None = None,
) -> _ScanTaskResult:
    metadata_result = _read_metadata_for_scan(path, timings=timings)
    if metadata_result is None:
        return _ScanTaskResult(path=path, replace_existing=replace_existing, track=None)
    _audio, metadata = metadata_result
    sidecar_started = time.perf_counter()
    signature = get_audio_file_signature(
        path,
        lyrics_lookup_subdir,
        metadata=metadata,
        lyrics_file_pattern=lyrics_file_pattern,
        timing_hook=None if timings is None else timings.record,
        count_hook=None if timings is None else timings.record,
    )
    if timings is not None:
        timings.record("sidecar_lookup_s", time.perf_counter() - sidecar_started)
    track = new_fs_track_from_path(
        path,
        signature=signature,
        lyrics_lookup_subdir=lyrics_lookup_subdir,
        lyrics_file_pattern=lyrics_file_pattern,
        metadata=metadata,
        timing_hook=None if timings is None else timings.record,
    )
    return _ScanTaskResult(path=path, replace_existing=replace_existing, track=track)


class LibraryScanner(QThread):
    progress_signal = Signal(int, int, str, float)     # scanned, total, current path, elapsed seconds
    finished_signal = Signal(bool, str)    # ok, message

    def __init__(
        self,
        db_path: str,
        directories: list[str],
        *,
        excluded_paths: str = "",
        excluded_patterns: str = "",
        lyrics_lookup_subdir: str = "",
        lyrics_file_pattern: str = "",
    ):
        super().__init__()
        self.db_path = db_path
        self.directories = directories
        self.excluded_paths = excluded_paths
        self.excluded_patterns = excluded_patterns
        self.lyrics_lookup_subdir = lyrics_lookup_subdir
        self.lyrics_file_pattern = lyrics_file_pattern

    def run(self):
        db = None
        started_at = time.perf_counter()
        timings = _ScanTimingStats()
        sidecar_lookup_cache = SidecarLookupCache()
        try:
            # IMPORTANT: open db connection inside this thread
            db = sqlite3.connect(self.db_path)
            db.row_factory = sqlite3.Row

            existing_index = get_library_scan_index(db)
            discovery_started = time.perf_counter()
            paths = iter_audio_paths(
                self.directories,
                excluded_paths=self.excluded_paths,
                excluded_patterns=self.excluded_patterns,
            )
            timings.record("path_discovery_s", time.perf_counter() - discovery_started)
            total = len(paths)
            scanned = 0
            unchanged = 0
            updated = 0
            removed = 0
            worker_failures = 0

            current_path_set = set(paths)
            removed_paths = [path for path in existing_index.keys() if path not in current_path_set]
            removed = len(removed_paths)

            # Build orphan index *before* deleting removed tracks so we can
            # transfer lyrics to new tracks that match by metadata.
            orphan_index = get_orphan_lyrics_index(db, removed_paths)
            reattached = 0

            batch = []
            pending_replacements: list[str] = []
            max_workers = _scan_worker_count()
            max_pending = max_workers * LIBRARY_SCAN_MAX_PENDING_MULTIPLIER
            futures: dict[Future[_ScanTaskResult], None] = {}
            executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="library-scan")
            executor_shutdown_wait = True

            def cancel_scan() -> None:
                nonlocal executor_shutdown_wait
                executor_shutdown_wait = False
                executor.shutdown(wait=False, cancel_futures=True)
                if db is not None:
                    db.rollback()
                self.finished_signal.emit(False, "Library scan cancelled.")

            def flush_batch(current_path: str) -> None:
                if not batch and not pending_replacements:
                    return
                flush_started = time.perf_counter()
                with db:
                    delete_tracks_by_paths(db, pending_replacements, commit=False)
                    add_tracks(db, batch, commit=False)
                timings.record("db_flush_s", time.perf_counter() - flush_started)
                batch.clear()
                pending_replacements.clear()
                self.progress_signal.emit(scanned, total, current_path, time.perf_counter() - started_at)

            def handle_scan_result(result: _ScanTaskResult) -> None:
                nonlocal reattached, updated
                if result.replace_existing:
                    pending_replacements.append(result.path)
                t = result.track
                if t is None:
                    return

                if orphan_index and not t.txt_lyrics and not t.lrc_lyrics:
                    key = (
                        prepare_input(t.title),
                        prepare_input(t.artist),
                        round(t.duration),
                    )
                    orphan = orphan_index.pop(key, None)
                    if orphan is not None:
                        t = dataclasses.replace(
                            t,
                            txt_lyrics=orphan[0],
                            lrc_lyrics=orphan[1],
                            instrumental=orphan[2],
                        )
                        reattached += 1
                        logger.info("Reattached orphan lyrics to: %s", result.path)

                batch.append(t)
                updated += 1

            def drain_completed(*, block: bool) -> None:
                nonlocal scanned
                if not futures:
                    return
                done, _pending = wait(
                    futures,
                    timeout=None if block else 0,
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    futures.pop(future, None)
                    scanned += 1
                    try:
                        result = future.result()
                    except Exception as exc:
                        worker_failures += 1
                        logger.warning("Skipping audio file during scan worker failure: %s", exc)
                        if scanned % 200 == 0:
                            self.progress_signal.emit(scanned, total, "", time.perf_counter() - started_at)
                        continue
                    handle_scan_result(result)
                    if len(batch) >= 100:
                        flush_batch(result.path)
                    elif scanned % 200 == 0:
                        self.progress_signal.emit(scanned, total, result.path, time.perf_counter() - started_at)

            try:
                for p in paths:
                    if self.isInterruptionRequested():
                        cancel_scan()
                        return

                    while len(futures) >= max_pending:
                        if self.isInterruptionRequested():
                            cancel_scan()
                            return
                        drain_completed(block=True)

                    existing = existing_index.get(p)
                    if existing is not None:
                        existing_signature, existing_metadata, existing_has_content = existing
                        if not existing_has_content:
                            fast_started = time.perf_counter()
                            try:
                                stat = os.stat(p)
                            except OSError:
                                stat = None
                            timings.record("audio_fast_path_s", time.perf_counter() - fast_started)
                            timings.record("audio_fast_path_count", 1)
                            current_signature = (
                                float(stat.st_mtime) if stat is not None else None,
                                int(stat.st_size) if stat is not None else None,
                            )
                            if existing_signature == current_signature:
                                timings.record("audio_fast_path_hit_count", 1)
                                scanned += 1
                                unchanged += 1
                                if scanned % 200 == 0:
                                    self.progress_signal.emit(scanned, total, p, time.perf_counter() - started_at)
                                drain_completed(block=False)
                                continue

                        signature_started = time.perf_counter()
                        signature = get_audio_file_signature(
                            p,
                            self.lyrics_lookup_subdir,
                            metadata=existing_metadata,
                            lyrics_file_pattern=self.lyrics_file_pattern,
                            sidecar_lookup_cache=sidecar_lookup_cache,
                            timing_hook=timings.record,
                            count_hook=timings.record,
                        )
                        timings.record("signature_check_s", time.perf_counter() - signature_started)
                        if existing_signature == signature:
                            scanned += 1
                            unchanged += 1
                            if scanned % 200 == 0:
                                self.progress_signal.emit(scanned, total, p, time.perf_counter() - started_at)
                            drain_completed(block=False)
                            continue

                    futures[
                        executor.submit(
                            _scan_track_for_path,
                            p,
                            replace_existing=existing is not None,
                            lyrics_lookup_subdir=self.lyrics_lookup_subdir,
                            lyrics_file_pattern=self.lyrics_file_pattern,
                            timings=timings,
                        )
                    ] = None
                    drain_completed(block=False)

                while futures:
                    if self.isInterruptionRequested():
                        cancel_scan()
                        return
                    drain_completed(block=True)
            finally:
                executor.shutdown(wait=executor_shutdown_wait, cancel_futures=not executor_shutdown_wait)

            if batch or pending_replacements:
                flush_started = time.perf_counter()
                with db:
                    delete_tracks_by_paths(db, pending_replacements, commit=False)
                    add_tracks(db, batch, commit=False)
                timings.record("db_flush_s", time.perf_counter() - flush_started)

            if removed_paths:
                flush_started = time.perf_counter()
                delete_tracks_by_paths(db, removed_paths)
                timings.record("db_flush_s", time.perf_counter() - flush_started)

            prune_started = time.perf_counter()
            prune_library(db)
            timings.record("db_flush_s", time.perf_counter() - prune_started)
            self.progress_signal.emit(scanned, total, "", time.perf_counter() - started_at)

            total_elapsed = time.perf_counter() - started_at
            logger.info(
                "Library scan summary: %d discovered, %d scanned, %d unchanged, %d updated, %d removed, %d worker failures",
                total,
                scanned,
                unchanged,
                updated,
                removed,
                worker_failures,
            )
            logger.info("Library scan path discovery time: %.3fs", timings.path_discovery_s)
            logger.info(
                "Library scan audio-only fast path time: %.3fs (%d attempts, %d hits)",
                timings.audio_fast_path_s,
                timings.audio_fast_path_count,
                timings.audio_fast_path_hit_count,
            )
            logger.info(
                "Library scan signature check time: %.3fs (%d checks)",
                timings.signature_check_s,
                timings.signature_check_count,
            )
            logger.info(
                "Library scan signature audio stat time: %.3fs",
                timings.signature_audio_stat_s,
            )
            logger.info(
                "Library scan signature sidecar stat time: %.3fs (%d candidates)",
                timings.signature_sidecar_stat_s,
                timings.signature_sidecar_candidate_count,
            )
            logger.info(
                "Library scan metadata read time: %.3fs (%d reads)",
                timings.metadata_read_s,
                timings.metadata_read_count,
            )
            logger.info(
                "Library scan embedded lyrics read time: %.3fs (%d reads)",
                timings.embedded_lyrics_read_s,
                timings.embedded_lyrics_read_count,
            )
            logger.info(
                "Library scan sidecar lookup time: %.3fs (%d lookups)",
                timings.sidecar_lookup_s,
                timings.sidecar_lookup_count,
            )
            logger.info(
                "Library scan DB flush time: %.3fs (%d flushes)",
                timings.db_flush_s,
                timings.db_flush_count,
            )
            if total_elapsed > 0:
                logger.info(
                    "Library scan average throughput: %.2f tracks/sec (%d tracks in %.2fs)",
                    scanned / total_elapsed,
                    scanned,
                    total_elapsed,
                )

            msg = f"Library scanning complete. Updated {updated}, unchanged {unchanged}, removed {removed}."
            if reattached:
                msg += f" Reattached lyrics for {reattached} moved file(s)."
            self.finished_signal.emit(True, msg)
        except Exception as e:
            self.finished_signal.emit(False, f"Scan failed: {e}")
        finally:
            if db is not None:
                db.close()
