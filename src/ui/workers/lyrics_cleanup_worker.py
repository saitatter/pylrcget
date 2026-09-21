from __future__ import annotations

import logging
import sqlite3

from PySide6.QtCore import QThread, Signal

from db.queries import (
    clear_track_dirty_lyrics,
    clear_tracks_lyrics,
    get_config,
    get_track_by_id,
)
from ui.services.lyrics_cleanup_service import LyricsCleanupOptions, apply_file_cleanup

logger = logging.getLogger(__name__)


class LyricsCleanupWorker(QThread):
    progress = Signal(int, int, str, str)
    itemFinished = Signal(int, object)
    finishedCleanup = Signal(bool, str, dict)

    def __init__(self, db_path: str, track_ids: list[int], options: LyricsCleanupOptions, parent=None) -> None:
        super().__init__(parent)
        self.db_path = db_path
        self.track_ids = list(dict.fromkeys(int(track_id) for track_id in track_ids if track_id is not None))
        self.options = options

    def run(self) -> None:
        db = None
        total = len(self.track_ids)
        cleaned = 0
        failed = 0
        cancelled = False

        try:
            db = sqlite3.connect(self.db_path, timeout=15.0)
            db.row_factory = sqlite3.Row
            config = get_config(db)

            for index, track_id in enumerate(self.track_ids, start=1):
                if self.isInterruptionRequested():
                    cancelled = True
                    break

                label = f"Track {track_id}"
                try:
                    track = get_track_by_id(db, track_id)
                    label = f"{track.artist_name} — {track.title}".strip(" —") or label
                    result = apply_file_cleanup(track, config, self.options)
                    if result.error is not None:
                        raise result.error

                    if self.options.clear_library:
                        clear_tracks_lyrics(
                            db,
                            [track_id],
                            clear_drafts=self.options.discard_drafts,
                            clear_txt=self.options.clear_txt,
                            clear_lrc=self.options.clear_lrc,
                        )
                    elif self.options.discard_drafts:
                        clear_track_dirty_lyrics(db, track_id)

                    cleaned += 1
                    payload = {
                        "track_id": track_id,
                        "status": "cleaned",
                        "deleted_sidecars": result.deleted_sidecars,
                        "embedded_cleared": result.embedded_cleared,
                        "message": "Lyrics cleared.",
                    }
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    logger.warning("Failed to clean lyrics for track %s: %s", track_id, exc)
                    payload = {
                        "track_id": track_id,
                        "status": "failed",
                        "error": exc,
                        "message": str(exc),
                    }

                self.itemFinished.emit(track_id, payload)
                self.progress.emit(index, total, label, payload["message"])
        except Exception as exc:
            logger.exception("Lyrics cleanup worker failed")
            stats = {"cleaned": cleaned, "failed": failed, "total": total, "cancelled": cancelled}
            self.finishedCleanup.emit(False, f"Clear lyrics failed: {exc}", stats)
            return
        finally:
            if db is not None:
                db.close()

        stats = {"cleaned": cleaned, "failed": failed, "total": total, "cancelled": cancelled}
        if cancelled:
            summary = f"Clear lyrics cancelled. {cleaned} cleared, {failed} failed."
        else:
            summary = f"Lyrics cleared. {cleaned} cleared, {failed} failed."
        self.finishedCleanup.emit(not cancelled and failed == 0, summary, stats)
