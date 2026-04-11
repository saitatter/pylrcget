from __future__ import annotations

import sqlite3
import time
from typing import TypedDict

from PySide6.QtCore import QObject, QThread, Signal

from db.models import Track
from db.queries import get_config, get_track_by_id
from ui.services.lyrics_download_service import download_track_lyrics


class BulkDownloadStats(TypedDict):
    total: int
    ok: int
    failed: int
    cancelled: bool


class BulkLyricsDownloadWorker(QThread):
    progress = Signal(int, int, str, str, float)  # current, total, track label, status, elapsed seconds
    itemFinished = Signal(int, bool, str, str)  # track_id, ok, track label, message
    finishedBatch = Signal(bool, str, dict)  # ok, message, stats dict

    def __init__(
        self,
        db_path: str,
        track_ids: list[int],
        lrclib_instance: str,
        *,
        download_mode: str = "prefer_synced",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.db_path = db_path
        self.track_ids = [int(t) for t in track_ids]
        self.lrclib_instance = lrclib_instance
        self.download_mode = (download_mode or "prefer_synced").strip() or "prefer_synced"

    def run(self) -> None:
        total = len(self.track_ids)
        started_at = time.perf_counter()
        ok_count = 0
        fail_count = 0
        cancelled = False
        request_delay_s = 0.35
        db = None
        try:
            db = sqlite3.connect(self.db_path, timeout=15.0)
            db.row_factory = sqlite3.Row
            config = get_config(db)
            for idx, track_id in enumerate(self.track_ids, start=1):
                if self.isInterruptionRequested():
                    cancelled = True
                    break
                if idx > 1:
                    time.sleep(request_delay_s)

                current_label = {"value": f"Track {idx}/{total}"}
                track: Track | None = None
                try:
                    track = get_track_by_id(db, track_id)
                    title = (track.title or "").strip()
                    artist = (track.artist_name or "").strip()
                    label = f"{artist} - {title}".strip(" -")
                    if label:
                        current_label["value"] = label
                except Exception:
                    pass

                self.progress.emit(
                    idx - 1,
                    total,
                    current_label["value"],
                    "Preparing download...",
                    time.perf_counter() - started_at,
                )

                def _progress(status: str, i: int = idx, t: int = total) -> None:
                    self.progress.emit(
                        i - 1,
                        t,
                        current_label["value"],
                        status,
                        time.perf_counter() - started_at,
                    )

                ok, msg, tid, label = download_track_lyrics(
                    self.db_path,
                    track_id,
                    self.lrclib_instance,
                    download_mode=self.download_mode,
                    progress_callback=_progress,
                    db=db,
                    config=config,
                    track=track,
                )
                if label:
                    current_label["value"] = label

                if ok:
                    ok_count += 1
                else:
                    fail_count += 1

                self.itemFinished.emit(int(tid), bool(ok), label or f"Track {idx}/{total}", msg)
                self.progress.emit(
                    idx,
                    total,
                    label or f"Track {idx}/{total}",
                    msg,
                    time.perf_counter() - started_at,
                )
        finally:
            if db is not None:
                db.close()

        stats: BulkDownloadStats = {
            "total": total,
            "ok": ok_count,
            "failed": fail_count,
            "cancelled": cancelled,
        }
        if cancelled:
            self.finishedBatch.emit(False, "Lyrics download cancelled.", stats)
        else:
            self.finishedBatch.emit(True, f"Finished lyrics download. Success: {ok_count}, Failed: {fail_count}.", stats)
