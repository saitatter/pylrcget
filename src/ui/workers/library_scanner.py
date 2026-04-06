# ui/library_scanner.py (or wherever LibraryScanner is defined)
import sqlite3
import time
from PySide6.QtCore import QThread, Signal

from library.scan_library import (
    get_audio_file_signature,
    iter_audio_paths_with_directory_cache,
    new_fs_track_from_path,
)
from db.database import (
    add_tracks,
    delete_tracks_by_paths,
    get_library_file_index,
    get_scan_cache_meta,
    get_scan_directory_index,
    prune_library,
    replace_scan_directory_index,
    set_scan_cache_meta,
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
    ):
        super().__init__()
        self.db_path = db_path
        self.directories = directories
        self.excluded_paths = excluded_paths
        self.excluded_patterns = excluded_patterns

    def run(self):
        db = None
        started_at = time.perf_counter()
        try:
            # IMPORTANT: open db connection inside this thread
            db = sqlite3.connect(self.db_path)
            db.row_factory = sqlite3.Row

            existing_index = get_library_file_index(db)
            previous_excluded_paths = get_scan_cache_meta(db, "excluded_paths")
            previous_excluded_patterns = get_scan_cache_meta(db, "excluded_patterns")
            cache_compatible = (
                previous_excluded_paths == self.excluded_paths
                and previous_excluded_patterns == self.excluded_patterns
            )
            cached_directory_mtimes = get_scan_directory_index(db) if cache_compatible else {}
            paths, directory_mtimes = iter_audio_paths_with_directory_cache(
                self.directories,
                existing_paths=list(existing_index.keys()),
                cached_directory_mtimes=cached_directory_mtimes,
                excluded_paths=self.excluded_paths,
                excluded_patterns=self.excluded_patterns,
            )
            total = len(paths)
            scanned = 0
            unchanged = 0
            updated = 0
            removed = 0

            current_path_set = set(paths)
            removed_paths = [path for path in existing_index.keys() if path not in current_path_set]
            if removed_paths:
                delete_tracks_by_paths(db, removed_paths)
                removed = len(removed_paths)

            batch = []
            pending_replacements: list[str] = []
            for p in paths:
                if self.isInterruptionRequested():
                    if db is not None:
                        db.rollback()
                    self.finished_signal.emit(False, "Library scan cancelled.")
                    return

                scanned += 1
                signature = get_audio_file_signature(p)
                if existing_index.get(p) == signature:
                    unchanged += 1
                    if scanned % 200 == 0:
                        self.progress_signal.emit(scanned, total, p, time.perf_counter() - started_at)
                    continue

                if p in existing_index:
                    pending_replacements.append(p)

                t = new_fs_track_from_path(p)

                if t is not None:
                    batch.append(t)
                    updated += 1

                if len(batch) >= 100:
                    db.execute("BEGIN")
                    try:
                        delete_tracks_by_paths(db, pending_replacements, commit=False)
                        add_tracks(db, batch, commit=False)
                        db.commit()
                    except Exception:
                        db.rollback()
                        raise
                    batch.clear()
                    pending_replacements.clear()
                    self.progress_signal.emit(scanned, total, p, time.perf_counter() - started_at)

                if scanned % 200 == 0:
                    self.progress_signal.emit(scanned, total, p, time.perf_counter() - started_at)

            if batch or pending_replacements:
                db.execute("BEGIN")
                try:
                    delete_tracks_by_paths(db, pending_replacements, commit=False)
                    add_tracks(db, batch, commit=False)
                    db.commit()
                except Exception:
                    db.rollback()
                    raise

            prune_library(db)
            replace_scan_directory_index(db, directory_mtimes)
            set_scan_cache_meta(db, "excluded_paths", self.excluded_paths)
            set_scan_cache_meta(db, "excluded_patterns", self.excluded_patterns)
            db.close()
            self.progress_signal.emit(scanned, total, "", time.perf_counter() - started_at)
            self.finished_signal.emit(
                True,
                f"Library scanning complete. Updated {updated}, unchanged {unchanged}, removed {removed}.",
            )
        except Exception as e:
            if db is not None:
                db.close()
            self.finished_signal.emit(False, f"Scan failed: {e}")
