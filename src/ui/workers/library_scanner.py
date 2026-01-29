# ui/library_scanner.py (or wherever LibraryScanner is defined)
import sqlite3
from PySide6.QtCore import QThread, Signal

from library.scan_library import iter_audio_paths, new_fs_track_from_path
from db.database import clean_library, add_tracks  # or add_tracks_bulk

class LibraryScanner(QThread):
    progress_signal = Signal(int, int)     # scanned, total
    finished_signal = Signal(bool, str)    # ok, message

    def __init__(self, db_path: str, directories: list[str]):
        super().__init__()
        self.db_path = db_path
        self.directories = directories

    def run(self):
        try:
            paths = iter_audio_paths(self.directories)
            total = len(paths)
            scanned = 0

            # IMPORTANT: open db connection inside this thread
            db = sqlite3.connect(self.db_path)
            db.row_factory = sqlite3.Row

            clean_library(db)

            batch = []
            for p in paths:
                t = new_fs_track_from_path(p)
                scanned += 1

                if t is not None:
                    batch.append(t)

                if len(batch) >= 100:
                    add_tracks(db, batch)   # later replace with add_tracks_bulk
                    batch.clear()
                    self.progress_signal.emit(scanned, total)

                if scanned % 200 == 0:
                    self.progress_signal.emit(scanned, total)

            if batch:
                add_tracks(db, batch)

            db.close()
            self.progress_signal.emit(scanned, total)
            self.finished_signal.emit(True, "Library scanning complete!")
        except Exception as e:
            self.finished_signal.emit(False, f"Scan failed: {e}")
