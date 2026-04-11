from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal

from ui.workers.lyrics_download_worker import download_track_lyrics


class BulkLyricsDownloadWorker(QThread):
    progress = Signal(int, int, str, str, float)  # current, total, track label, status, elapsed seconds
    itemFinished = Signal(int, bool, str)  # track_id, ok, message
    finishedBatch = Signal(bool, str, object)  # ok, message, stats dict

    def __init__(
        self,
        db_path: str,
        track_ids: list[int],
        lrclib_instance: str,
        *,
        download_mode: str = "prefer_synced",
        parent=None,
    ):
        super().__init__(parent)
        self.db_path = db_path
        self.track_ids = [int(t) for t in track_ids]
        self.lrclib_instance = lrclib_instance
        self.download_mode = (download_mode or "prefer_synced").strip() or "prefer_synced"

    def run(self):
        total = len(self.track_ids)
        started_at = time.perf_counter()
        ok_count = 0
        fail_count = 0
        cancelled = False

        for idx, track_id in enumerate(self.track_ids, start=1):
            if self.isInterruptionRequested():
                cancelled = True
                break

            self.progress.emit(
                idx - 1,
                total,
                f"Track {idx}/{total}",
                "Preparing download...",
                time.perf_counter() - started_at,
            )

            current_label = {"value": f"Track {idx}/{total}"}

            def _progress(status: str, i=idx, t=total):
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
            )
            if label:
                current_label["value"] = label

            if ok:
                ok_count += 1
            else:
                fail_count += 1

            self.itemFinished.emit(int(tid), bool(ok), msg)
            self.progress.emit(
                idx,
                total,
                label or f"Track {idx}/{total}",
                msg,
                time.perf_counter() - started_at,
            )

        stats = {
            "total": total,
            "ok": ok_count,
            "failed": fail_count,
            "cancelled": cancelled,
        }
        if cancelled:
            self.finishedBatch.emit(False, "Lyrics download cancelled.", stats)
        else:
            self.finishedBatch.emit(True, f"Finished lyrics download. Success: {ok_count}, Failed: {fail_count}.", stats)
