from __future__ import annotations

import logging
import sqlite3

from PySide6.QtCore import QThread, Signal

from db.queries import get_config, get_track_by_id
from ui.services.lyrics_download_service import sync_track_outputs_with_result

logger = logging.getLogger(__name__)


class TrackOutputSyncWorker(QThread):
    progress = Signal(int, int, str, str)
    itemFinished = Signal(int, object)
    finishedSync = Signal(bool, str, dict)

    def __init__(self, db_path: str, track_ids: list[int], parent=None) -> None:
        super().__init__(parent)
        self.db_path = db_path
        self.track_ids = [int(track_id) for track_id in track_ids if track_id is not None]

    def run(self) -> None:
        db = None
        total = len(self.track_ids)
        ok_count = 0
        fail_count = 0
        cancelled = False

        try:
            db = sqlite3.connect(self.db_path, timeout=15.0)
            db.row_factory = sqlite3.Row
            config = get_config(db)

            for idx, track_id in enumerate(self.track_ids, start=1):
                if self.isInterruptionRequested():
                    cancelled = True
                    break

                self.progress.emit(idx, total, f"Track {track_id}", "Syncing lyrics outputs...")
                try:
                    track = get_track_by_id(db, int(track_id))
                    result = sync_track_outputs_with_result(track, config)
                except Exception as exc:  # noqa: BLE001
                    fail_count += 1
                    logger.warning("Failed to sync outputs for track %s: %s", track_id, exc)
                    self.itemFinished.emit(int(track_id), {"track_id": int(track_id), "error": exc})
                    continue

                item_ok = result.sidecar_error is None and result.embed_error is None
                ok_count += int(item_ok)
                fail_count += int(not item_ok)
                self.itemFinished.emit(
                    int(track_id),
                    {
                        "track_id": int(track_id),
                        "sidecar_paths": result.sidecar_paths,
                        "sidecar_error": result.sidecar_error,
                        "embedded": result.embedded,
                        "embed_error": result.embed_error,
                    },
                )

        except Exception as exc:
            logger.exception("Track output sync worker failed")
            stats = {"ok": ok_count, "failed": fail_count, "total": total, "cancelled": cancelled}
            self.finishedSync.emit(False, f"Lyrics output sync failed: {exc}", stats)
            return
        finally:
            if db is not None:
                db.close()

        stats = {"ok": ok_count, "failed": fail_count, "total": total, "cancelled": cancelled}
        summary = (
            f"Lyrics output sync cancelled. {ok_count} completed, {fail_count} failed."
            if cancelled
            else f"Lyrics output sync complete. {ok_count} completed, {fail_count} failed."
        )
        self.finishedSync.emit(not cancelled and fail_count == 0, summary, stats)
