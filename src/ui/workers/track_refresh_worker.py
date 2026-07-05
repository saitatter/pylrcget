from __future__ import annotations

import logging
import sqlite3

from PySide6.QtCore import QThread, Signal

from db.queries import refresh_track_from_file

logger = logging.getLogger(__name__)


class TrackRefreshWorker(QThread):
    progress = Signal(int, int, str, str)
    finishedRefresh = Signal(bool, str, dict)

    def __init__(self, db_path: str, track_ids: list[int], parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.track_ids = [int(track_id) for track_id in track_ids if track_id is not None]

    def run(self) -> None:
        db = None
        refreshed_ids: list[int] = []
        removed_ids: list[int] = []
        failed_ids: list[int] = []
        cancelled = False
        total = len(self.track_ids)

        try:
            db = sqlite3.connect(self.db_path, timeout=15.0)
            db.row_factory = sqlite3.Row

            for idx, track_id in enumerate(self.track_ids, start=1):
                if self.isInterruptionRequested():
                    cancelled = True
                    break

                self.progress.emit(idx, total, f"Track {track_id}", "Refreshing from disk...")
                try:
                    refreshed = refresh_track_from_file(db, track_id)
                except Exception as exc:
                    failed_ids.append(track_id)
                    logger.warning("Failed to refresh track %s: %s", track_id, exc)
                    continue

                if refreshed is None:
                    removed_ids.append(track_id)
                else:
                    refreshed_ids.append(track_id)

        except Exception as exc:
            logger.exception("Track refresh worker failed: %s", exc)
            stats = {
                "refreshed": refreshed_ids,
                "removed": removed_ids,
                "failed": failed_ids,
                "cancelled": cancelled,
                "total": total,
            }
            self.finishedRefresh.emit(False, f"Track refresh failed: {exc}", stats)
            return
        finally:
            if db is not None:
                db.close()

        stats = {
            "refreshed": refreshed_ids,
            "removed": removed_ids,
            "failed": failed_ids,
            "cancelled": cancelled,
            "total": total,
        }
        refreshed_count = len(refreshed_ids)
        removed_count = len(removed_ids)
        failed_count = len(failed_ids)
        if cancelled:
            summary = f"Track refresh cancelled. {refreshed_count} refreshed, {removed_count} removed, {failed_count} failed."
        else:
            summary = f"Refreshed {refreshed_count} track(s). Removed {removed_count} missing track(s)."
            if failed_count:
                summary = f"{summary} {failed_count} failed."
        self.finishedRefresh.emit(not cancelled and failed_count == 0, summary, stats)
