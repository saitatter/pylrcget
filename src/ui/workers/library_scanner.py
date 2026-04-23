# ui/library_scanner.py (or wherever LibraryScanner is defined)
import dataclasses
import logging
import sqlite3
import time
from PySide6.QtCore import QThread, Signal

from core.utils import prepare_input
from library.scan_library import (
    get_audio_file_signature,
    iter_audio_paths,
    new_fs_track_from_path,
)
from db.database import (
    add_tracks,
    delete_tracks_by_paths,
    get_library_file_index,
    get_orphan_lyrics_index,
    prune_library,
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
    ):
        super().__init__()
        self.db_path = db_path
        self.directories = directories
        self.excluded_paths = excluded_paths
        self.excluded_patterns = excluded_patterns
        self.lyrics_lookup_subdir = lyrics_lookup_subdir

    def run(self):
        db = None
        started_at = time.perf_counter()
        try:
            # IMPORTANT: open db connection inside this thread
            db = sqlite3.connect(self.db_path)
            db.row_factory = sqlite3.Row

            existing_index = get_library_file_index(db)
            paths = iter_audio_paths(
                self.directories,
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
            removed = len(removed_paths)

            # Build orphan index *before* deleting removed tracks so we can
            # transfer lyrics to new tracks that match by metadata.
            orphan_index = get_orphan_lyrics_index(db, removed_paths)
            reattached = 0

            batch = []
            pending_replacements: list[str] = []
            for p in paths:
                if self.isInterruptionRequested():
                    if db is not None:
                        db.rollback()
                    self.finished_signal.emit(False, "Library scan cancelled.")
                    return

                scanned += 1
                signature = get_audio_file_signature(p, self.lyrics_lookup_subdir)
                if existing_index.get(p) == signature:
                    unchanged += 1
                    if scanned % 200 == 0:
                        self.progress_signal.emit(scanned, total, p, time.perf_counter() - started_at)
                    continue

                if p in existing_index:
                    pending_replacements.append(p)

                t = new_fs_track_from_path(
                    p,
                    signature=signature,
                    lyrics_lookup_subdir=self.lyrics_lookup_subdir,
                )

                if t is not None:
                    # Try to reattach orphan lyrics if the new track has none
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
                            logger.info("Reattached orphan lyrics to: %s", p)

                    batch.append(t)
                    updated += 1

                if len(batch) >= 100:
                    with db:
                        delete_tracks_by_paths(db, pending_replacements, commit=False)
                        add_tracks(db, batch, commit=False)
                    batch.clear()
                    pending_replacements.clear()
                    self.progress_signal.emit(scanned, total, p, time.perf_counter() - started_at)

                if scanned % 200 == 0:
                    self.progress_signal.emit(scanned, total, p, time.perf_counter() - started_at)

            if batch or pending_replacements:
                with db:
                    delete_tracks_by_paths(db, pending_replacements, commit=False)
                    add_tracks(db, batch, commit=False)

            if removed_paths:
                delete_tracks_by_paths(db, removed_paths)

            prune_library(db)
            self.progress_signal.emit(scanned, total, "", time.perf_counter() - started_at)

            msg = f"Library scanning complete. Updated {updated}, unchanged {unchanged}, removed {removed}."
            if reattached:
                msg += f" Reattached lyrics for {reattached} moved file(s)."
            self.finished_signal.emit(True, msg)
        except Exception as e:
            self.finished_signal.emit(False, f"Scan failed: {e}")
        finally:
            if db is not None:
                db.close()
