# ui/library_scanner.py (or wherever LibraryScanner is defined)
import dataclasses
import logging
import os
import sqlite3
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

from core.models import FsTrack
from core.utils import prepare_input
from db.database import (
    delete_tracks_by_paths,
    get_library_scan_index,
    get_orphan_lyrics_index,
    get_track_ids_by_paths,
    get_track_scan_state_index,
    prune_library,
    upsert_track_scan_states,
)
from db.query_modules.track_queries import TrackBatchInserter
from library.scan_library import (
    SidecarLookupCache,
    get_audio_signature,
    get_sidecar_scan_state,
    get_audio_file_signature,
    iter_audio_paths_with_signatures_and_audio_signatures,
    new_fs_track_from_path,
    read_audio_metadata_for_scan,
    read_lyrics_for_scan,
)
from library.scan_state import (
    TRACK_SCAN_STATE_SIGNATURE_VERSION,
    TrackScanState,
)

logger = logging.getLogger(__name__)
LIBRARY_SCAN_MAX_WORKERS = 4
LIBRARY_SCAN_MAX_PENDING_MULTIPLIER = 4
LIBRARY_SCAN_PROGRESS_INTERVAL_S = 0.75
LIBRARY_SCAN_BATCH_SIZE = 500


def _scan_mode_allows_sidecar(mode: str | None) -> bool:
    normalized = (mode or "both").strip().lower()
    return normalized not in {"embedded_only", "embedded-only"}


def _scan_mode_allows_embedded(mode: str | None) -> bool:
    normalized = (mode or "both").strip().lower()
    return normalized not in {"sidecar_only", "sidecar-only"}


class _ScanTimingStats:
    def __init__(self) -> None:
        self.path_discovery_s = 0.0
        self.audio_fast_path_s = 0.0
        self.signature_check_s = 0.0
        self.signature_lookup_s = 0.0
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
            elif field_name == "signature_lookup_s":
                pass
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
    scan_state: TrackScanState | None = None


def _read_metadata_for_scan(path: str, *, timings: _ScanTimingStats | None = None):
    started_at = time.perf_counter()
    try:
        return read_audio_metadata_for_scan(path)
    except Exception as exc:  # noqa: BLE001
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
    scan_lyrics_source_mode: str,
    audio_signature: tuple[float | None, int | None] | None = None,
    audio_signature_ns: tuple[int | None, int | None] | None = None,
    sidecar_lookup_cache: SidecarLookupCache | None = None,
    timings: _ScanTimingStats | None = None,
) -> _ScanTaskResult:
    metadata_result = _read_metadata_for_scan(path, timings=timings)
    if metadata_result is None:
        return _ScanTaskResult(path=path, replace_existing=replace_existing, track=None)
    audio, metadata = metadata_result
    sidecar_state = get_sidecar_scan_state(
        path,
        lyrics_lookup_subdir,
        metadata=metadata,
        lyrics_file_pattern=lyrics_file_pattern,
        scan_lyrics_source_mode=scan_lyrics_source_mode,
        sidecar_lookup_cache=sidecar_lookup_cache,
        timing_hook=None if timings is None else timings.record,
    )
    sidecar_started = time.perf_counter()
    signature = get_audio_file_signature(
        path,
        lyrics_lookup_subdir,
        metadata=metadata,
        lyrics_file_pattern=lyrics_file_pattern,
        scan_lyrics_source_mode=scan_lyrics_source_mode,
        audio_signature=audio_signature,
        sidecar_lookup_cache=sidecar_lookup_cache,
        timing_hook=None if timings is None else timings.record,
        count_hook=None if timings is None else timings.record,
    )
    if timings is not None:
        timings.record("signature_lookup_s", time.perf_counter() - sidecar_started)
    lyrics_result = read_lyrics_for_scan(
        path,
        audio=audio,
        lyrics_lookup_subdir=lyrics_lookup_subdir,
        metadata=metadata,
        lyrics_file_pattern=lyrics_file_pattern,
        scan_lyrics_source_mode=scan_lyrics_source_mode,
        sidecar_lookup_cache=sidecar_lookup_cache,
        timing_hook=None if timings is None else timings.record,
    )
    track = new_fs_track_from_path(
        path,
        signature=signature,
        audio_signature=audio_signature,
        lyrics_lookup_subdir=lyrics_lookup_subdir,
        lyrics_file_pattern=lyrics_file_pattern,
        scan_lyrics_source_mode=scan_lyrics_source_mode,
        sidecar_lookup_cache=sidecar_lookup_cache,
        metadata=metadata,
        audio=audio,
        lyrics_result=lyrics_result,
        timing_hook=None if timings is None else timings.record,
    )
    if track is None:
        return _ScanTaskResult(path=path, replace_existing=replace_existing, track=None)
    audio_state = audio_signature_ns or get_audio_signature(path)
    use_embedded = _scan_mode_allows_embedded(scan_lyrics_source_mode)
    use_sidecar = _scan_mode_allows_sidecar(scan_lyrics_source_mode)
    scan_state = TrackScanState(
        track_id=0,
        audio_mtime_ns=audio_state[0],
        audio_size=audio_state[1],
        sidecar_signature=sidecar_state.signature,
        embedded_txt_present=lyrics_result.embedded_txt is not None if use_embedded else None,
        embedded_lrc_present=lyrics_result.embedded_lrc is not None if use_embedded else None,
        sidecar_txt_present=sidecar_state.txt_present if use_sidecar else None,
        sidecar_lrc_present=sidecar_state.lrc_present if use_sidecar else None,
        embedded_txt_lyrics=lyrics_result.embedded_txt if use_embedded else None,
        embedded_lrc_lyrics=lyrics_result.embedded_lrc if use_embedded else None,
        signature_version=TRACK_SCAN_STATE_SIGNATURE_VERSION,
        last_scan_at=time.time(),
    )
    return _ScanTaskResult(
        path=path,
        replace_existing=replace_existing,
        track=track,
        scan_state=scan_state,
    )


def _scan_sidecar_only_for_path(
    path: str,
    *,
    replace_existing: bool,
    metadata,
    previous_state: TrackScanState,
    sidecar_state,
    legacy_signature: tuple[float | None, int | None],
    lyrics_lookup_subdir: str,
    lyrics_file_pattern: str,
    scan_lyrics_source_mode: str,
    sidecar_lookup_cache: SidecarLookupCache,
    timings: _ScanTimingStats | None = None,
) -> _ScanTaskResult:
    if _scan_mode_allows_embedded(scan_lyrics_source_mode) and (
        previous_state.embedded_txt_present is None
        or previous_state.embedded_lrc_present is None
    ):
        return _ScanTaskResult(path=path, replace_existing=replace_existing, track=None)

    sidecar_lyrics = read_lyrics_for_scan(
        path,
        lyrics_lookup_subdir=lyrics_lookup_subdir,
        metadata=metadata,
        lyrics_file_pattern=lyrics_file_pattern,
        scan_lyrics_source_mode="sidecar_only",
        sidecar_lookup_cache=sidecar_lookup_cache,
        read_sidecar_txt=not (
            _scan_mode_allows_embedded(scan_lyrics_source_mode)
            and bool(previous_state.embedded_txt_present)
        ),
        read_sidecar_lrc=not (
            _scan_mode_allows_embedded(scan_lyrics_source_mode)
            and bool(previous_state.embedded_lrc_present)
        ),
        timing_hook=None if timings is None else timings.record,
    )
    use_embedded = _scan_mode_allows_embedded(scan_lyrics_source_mode)
    use_sidecar = _scan_mode_allows_sidecar(scan_lyrics_source_mode)
    embedded_txt = previous_state.embedded_txt_lyrics if use_embedded else None
    embedded_lrc = previous_state.embedded_lrc_lyrics if use_embedded else None
    sidecar_txt = sidecar_lyrics.sidecar_txt if use_sidecar else None
    sidecar_lrc = sidecar_lyrics.sidecar_lrc if use_sidecar else None
    # FsTrack is intentionally constructed here instead of opening the audio
    # file. Metadata is already represented by the DB index.
    track = FsTrack(
        file_path=path,
        file_name=os.path.basename(path),
        title=metadata.title,
        album=metadata.album,
        artist=metadata.artist,
        album_artist=metadata.album_artist,
        duration=metadata.duration,
        txt_lyrics=embedded_txt or sidecar_txt,
        lrc_lyrics=embedded_lrc or sidecar_lrc,
        track_number=metadata.track_number,
        modified_time=legacy_signature[0],
        file_size=legacy_signature[1],
    )
    state = dataclasses.replace(
        previous_state,
        audio_mtime_ns=previous_state.audio_mtime_ns,
        audio_size=previous_state.audio_size,
        sidecar_signature=sidecar_state.signature,
        embedded_txt_present=(previous_state.embedded_txt_present if use_embedded else None),
        embedded_lrc_present=(previous_state.embedded_lrc_present if use_embedded else None),
        sidecar_txt_present=sidecar_state.txt_present if use_sidecar else None,
        sidecar_lrc_present=sidecar_state.lrc_present if use_sidecar else None,
        embedded_txt_lyrics=embedded_txt,
        embedded_lrc_lyrics=embedded_lrc,
        signature_version=TRACK_SCAN_STATE_SIGNATURE_VERSION,
        last_scan_at=time.time(),
    )
    return _ScanTaskResult(
        path=path,
        replace_existing=replace_existing,
        track=track,
        scan_state=state,
    )


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
        scan_lyrics_source_mode: str = "both",
        scan_worker_count: int = LIBRARY_SCAN_MAX_WORKERS,
    ):
        super().__init__()
        self.db_path = db_path
        self.directories = directories
        self.excluded_paths = excluded_paths
        self.excluded_patterns = excluded_patterns
        self.lyrics_lookup_subdir = lyrics_lookup_subdir
        self.lyrics_file_pattern = lyrics_file_pattern
        self.scan_lyrics_source_mode = scan_lyrics_source_mode
        self.scan_worker_count = max(1, int(scan_worker_count or LIBRARY_SCAN_MAX_WORKERS))

    def run(self):
        db = None
        started_at = time.perf_counter()
        timings = _ScanTimingStats()
        sidecar_lookup_cache = SidecarLookupCache()
        last_progress_emit = started_at
        try:
            # IMPORTANT: open db connection inside this thread
            db = sqlite3.connect(self.db_path)
            db.row_factory = sqlite3.Row
            config_row = db.execute(
                "SELECT scan_lyrics_source_mode FROM config_data LIMIT 1"
            ).fetchone()
            if config_row is not None:
                self.scan_lyrics_source_mode = str(
                    config_row["scan_lyrics_source_mode"] or self.scan_lyrics_source_mode or "both"
                )
            logger.debug("Library scan lyrics source mode: %s", self.scan_lyrics_source_mode)

            existing_index = get_library_scan_index(db)
            scan_state_index = get_track_scan_state_index(db)
            existing_track_ids = get_track_ids_by_paths(db, list(existing_index))
            scan_state_by_path = {
                path: scan_state_index[track_id]
                for path, track_id in existing_track_ids.items()
                if track_id in scan_state_index
            }
            discovery_started = time.perf_counter()
            paths, discovered_signatures, discovered_audio_signatures = iter_audio_paths_with_signatures_and_audio_signatures(
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
            removed_paths = [path for path in existing_index if path not in current_path_set]
            removed = len(removed_paths)

            # Build orphan index *before* deleting removed tracks so we can
            # transfer lyrics to new tracks that match by metadata.
            orphan_index = get_orphan_lyrics_index(db, removed_paths)
            reattached = 0

            batch = []
            pending_replacements: list[str] = []
            pending_scan_states: dict[str, TrackScanState] = {}
            max_workers = self.scan_worker_count
            max_pending = max_workers * LIBRARY_SCAN_MAX_PENDING_MULTIPLIER
            futures: dict[Future[_ScanTaskResult], None] = {}
            executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="library-scan")
            executor_shutdown_wait = True
            batch_inserter = TrackBatchInserter(db)

            def cancel_scan() -> None:
                nonlocal executor_shutdown_wait
                executor_shutdown_wait = False
                executor.shutdown(wait=False, cancel_futures=True)
                if db is not None:
                    db.rollback()
                self.finished_signal.emit(False, "Library scan cancelled.")

            def flush_batch(current_path: str) -> None:
                if not batch and not pending_replacements and not pending_scan_states:
                    return
                flush_started = time.perf_counter()
                batch_paths = [track.file_path for track in batch]
                with db:
                    delete_tracks_by_paths(db, pending_replacements, commit=False)
                    batch_inserter.add_tracks(batch)
                    track_ids = get_track_ids_by_paths(db, batch_paths)
                    states = [
                        dataclasses.replace(state, track_id=track_ids.get(path, state.track_id))
                        for path, state in pending_scan_states.items()
                        if track_ids.get(path, state.track_id)
                    ]
                    upsert_track_scan_states(db, states, commit=False)
                timings.record("db_flush_s", time.perf_counter() - flush_started)
                batch.clear()
                pending_replacements.clear()
                pending_scan_states.clear()
                self.progress_signal.emit(scanned, total, current_path, time.perf_counter() - started_at)

            def maybe_emit_progress(current_path: str) -> None:
                nonlocal last_progress_emit
                now = time.perf_counter()
                if now - last_progress_emit < LIBRARY_SCAN_PROGRESS_INTERVAL_S:
                    return
                last_progress_emit = now
                self.progress_signal.emit(scanned, total, current_path, now - started_at)

            def handle_scan_result(result: _ScanTaskResult) -> None:
                nonlocal reattached, updated
                if result.replace_existing:
                    pending_replacements.append(result.path)
                t = result.track
                if t is None:
                    return
                if result.scan_state is not None:
                    pending_scan_states[result.path] = result.scan_state

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
                nonlocal scanned, worker_failures
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
                    except Exception as exc:  # noqa: BLE001
                        worker_failures += 1
                        logger.warning("Skipping audio file during scan worker failure: %s", exc)
                        maybe_emit_progress("")
                        continue
                    handle_scan_result(result)
                    if len(batch) >= LIBRARY_SCAN_BATCH_SIZE:
                        flush_batch(result.path)
                    else:
                        maybe_emit_progress(result.path)

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
                    previous_state = scan_state_by_path.get(p) if existing is not None else None
                    if existing is not None and previous_state is not None:
                        _existing_signature, existing_metadata, _existing_has_content = existing
                        current_audio_signature = discovered_audio_signatures.get(p) or get_audio_signature(p)
                        current_embedded_state_available = (
                            not _scan_mode_allows_embedded(self.scan_lyrics_source_mode)
                            or (
                                previous_state.embedded_txt_present is not None
                                and previous_state.embedded_lrc_present is not None
                            )
                        )
                        if (
                            previous_state.signature_version == TRACK_SCAN_STATE_SIGNATURE_VERSION
                            and current_embedded_state_available
                            and (previous_state.audio_mtime_ns, previous_state.audio_size) == current_audio_signature
                        ):
                            signature_started = time.perf_counter()
                            current_sidecar_state = get_sidecar_scan_state(
                                p,
                                self.lyrics_lookup_subdir,
                                metadata=existing_metadata,
                                lyrics_file_pattern=self.lyrics_file_pattern,
                                scan_lyrics_source_mode=self.scan_lyrics_source_mode,
                                sidecar_lookup_cache=sidecar_lookup_cache,
                                timing_hook=timings.record,
                            )
                            timings.record("signature_check_s", time.perf_counter() - signature_started)
                            if previous_state.sidecar_signature == current_sidecar_state.signature:
                                timings.record("audio_fast_path_s", 0.0000001)
                                timings.record("audio_fast_path_count", 1)
                                timings.record("audio_fast_path_hit_count", 1)
                                scanned += 1
                                unchanged += 1
                                maybe_emit_progress(p)
                                drain_completed(block=False)
                                continue

                            legacy_signature_started = time.perf_counter()
                            legacy_signature = get_audio_file_signature(
                                p,
                                self.lyrics_lookup_subdir,
                                metadata=existing_metadata,
                                lyrics_file_pattern=self.lyrics_file_pattern,
                                scan_lyrics_source_mode=self.scan_lyrics_source_mode,
                                audio_signature=discovered_signatures.get(p),
                                sidecar_lookup_cache=sidecar_lookup_cache,
                                timing_hook=timings.record,
                                count_hook=timings.record,
                            )
                            timings.record("signature_lookup_s", time.perf_counter() - legacy_signature_started)
                            sidecar_result = _scan_sidecar_only_for_path(
                                p,
                                replace_existing=True,
                                metadata=existing_metadata,
                                previous_state=previous_state,
                                sidecar_state=current_sidecar_state,
                                legacy_signature=legacy_signature,
                                lyrics_lookup_subdir=self.lyrics_lookup_subdir,
                                lyrics_file_pattern=self.lyrics_file_pattern,
                                scan_lyrics_source_mode=self.scan_lyrics_source_mode,
                                sidecar_lookup_cache=sidecar_lookup_cache,
                                timings=timings,
                            )
                            if sidecar_result.track is not None:
                                scanned += 1
                                handle_scan_result(sidecar_result)
                                if len(batch) >= LIBRARY_SCAN_BATCH_SIZE:
                                    flush_batch(p)
                                else:
                                    maybe_emit_progress(p)
                                drain_completed(block=False)
                                continue

                    if existing is not None and previous_state is None:
                        existing_signature, existing_metadata, existing_has_content = existing
                        legacy_signature_started = time.perf_counter()
                        legacy_signature = get_audio_file_signature(
                            p,
                            self.lyrics_lookup_subdir,
                            metadata=existing_metadata,
                            lyrics_file_pattern=self.lyrics_file_pattern,
                            scan_lyrics_source_mode=self.scan_lyrics_source_mode,
                            audio_signature=discovered_signatures.get(p),
                            sidecar_lookup_cache=sidecar_lookup_cache,
                            timing_hook=timings.record,
                            count_hook=timings.record,
                        )
                        timings.record("signature_check_s", time.perf_counter() - legacy_signature_started)
                        if existing_signature == legacy_signature:
                            current_sidecar_state = get_sidecar_scan_state(
                                p,
                                self.lyrics_lookup_subdir,
                                metadata=existing_metadata,
                                lyrics_file_pattern=self.lyrics_file_pattern,
                                scan_lyrics_source_mode=self.scan_lyrics_source_mode,
                                sidecar_lookup_cache=sidecar_lookup_cache,
                                timing_hook=timings.record,
                            )
                            track_id = existing_track_ids.get(p)
                            if track_id is not None:
                                use_embedded = _scan_mode_allows_embedded(self.scan_lyrics_source_mode)
                                pending_scan_states[p] = TrackScanState(
                                    track_id=track_id,
                                    audio_mtime_ns=discovered_audio_signatures.get(p, (None, None))[0],
                                    audio_size=discovered_audio_signatures.get(p, (None, None))[1],
                                    sidecar_signature=current_sidecar_state.signature,
                                    embedded_txt_present=False if use_embedded and not existing_has_content else None,
                                    embedded_lrc_present=False if use_embedded and not existing_has_content else None,
                                    sidecar_txt_present=current_sidecar_state.txt_present
                                    if _scan_mode_allows_sidecar(self.scan_lyrics_source_mode)
                                    else None,
                                    sidecar_lrc_present=current_sidecar_state.lrc_present
                                    if _scan_mode_allows_sidecar(self.scan_lyrics_source_mode)
                                    else None,
                                    signature_version=TRACK_SCAN_STATE_SIGNATURE_VERSION,
                                    last_scan_at=time.time(),
                                )
                            scanned += 1
                            unchanged += 1
                            maybe_emit_progress(p)
                            drain_completed(block=False)
                            continue

                    futures[
                        executor.submit(
                            _scan_track_for_path,
                            p,
                            replace_existing=existing is not None,
                            lyrics_lookup_subdir=self.lyrics_lookup_subdir,
                            lyrics_file_pattern=self.lyrics_file_pattern,
                            scan_lyrics_source_mode=self.scan_lyrics_source_mode,
                            audio_signature=discovered_signatures.get(p),
                            audio_signature_ns=discovered_audio_signatures.get(p),
                            sidecar_lookup_cache=sidecar_lookup_cache,
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
                flush_batch("")

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
            cumulative_worker_s = (
                timings.path_discovery_s
                + timings.audio_fast_path_s
                + timings.signature_check_s
                + timings.signature_lookup_s
                + timings.signature_audio_stat_s
                + timings.signature_sidecar_stat_s
                + timings.metadata_read_s
                + timings.embedded_lyrics_read_s
                + timings.sidecar_lookup_s
                + timings.db_flush_s
            )
            logger.info(
                "Library scan timing totals are cumulative worker time across workers; wall time is %.3fs.",
                total_elapsed,
            )
            logger.info(
                "Library scan cumulative worker time: %.3fs (%.2fx wall time)",
                cumulative_worker_s,
                (cumulative_worker_s / total_elapsed) if total_elapsed > 0 else 0.0,
            )
            if total_elapsed > 0:
                logger.info(
                    "Library scan average throughput: %.2f tracks/sec (%d tracks in %.2fs wall time)",
                    scanned / total_elapsed,
                    scanned,
                    total_elapsed,
                )
            logger.debug("Library scan path discovery cumulative worker time: %.3fs", timings.path_discovery_s)
            logger.debug(
                "Library scan audio-only fast path cumulative worker time: %.3fs (%d attempts, %d hits)",
                timings.audio_fast_path_s,
                timings.audio_fast_path_count,
                timings.audio_fast_path_hit_count,
            )
            logger.debug(
                "Library scan signature check cumulative worker time: %.3fs (%d checks)",
                timings.signature_check_s,
                timings.signature_check_count,
            )
            logger.debug(
                "Library scan signature audio stat cumulative worker time: %.3fs",
                timings.signature_audio_stat_s,
            )
            logger.debug(
                "Library scan signature sidecar stat cumulative worker time: %.3fs (%d candidates)",
                timings.signature_sidecar_stat_s,
                timings.signature_sidecar_candidate_count,
            )
            logger.debug(
                "Library scan metadata read cumulative worker time: %.3fs (%d reads)",
                timings.metadata_read_s,
                timings.metadata_read_count,
            )
            logger.debug(
                "Library scan embedded lyrics read cumulative worker time: %.3fs (%d reads)",
                timings.embedded_lyrics_read_s,
                timings.embedded_lyrics_read_count,
            )
            logger.debug(
                "Library scan signature lookup cumulative worker time: %.3fs",
                timings.signature_lookup_s,
            )
            logger.debug(
                "Library scan sidecar lookup cumulative worker time: %.3fs (%d lookups)",
                timings.sidecar_lookup_s,
                timings.sidecar_lookup_count,
            )
            logger.debug(
                "Library scan DB flush cumulative worker time: %.3fs (%d flushes)",
                timings.db_flush_s,
                timings.db_flush_count,
            )
            if not _scan_mode_allows_sidecar(self.scan_lyrics_source_mode) and (
                timings.sidecar_lookup_s > 0 or timings.signature_sidecar_stat_s > 0
            ):
                logger.warning(
                    "Library scan recorded sidecar timing while scan mode=%s; this suggests a caller/config mismatch.",
                    self.scan_lyrics_source_mode,
                )
            msg = f"Library scanning complete. Updated {updated}, unchanged {unchanged}, removed {removed}."
            if reattached:
                msg += f" Reattached lyrics for {reattached} moved file(s)."
            self.finished_signal.emit(True, msg)
        except Exception as e:  # noqa: BLE001
            self.finished_signal.emit(False, f"Scan failed: {e}")
        finally:
            if db is not None:
                db.close()
