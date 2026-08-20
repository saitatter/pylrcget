from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ui.services.lyrics_download_service import download_track_lyrics


class LyricsDownloadWorker(QThread):
    progress = Signal(str)
    finished = Signal(bool, str, int)  # ok, msg, track_id

    def __init__(
        self,
        db_path: str,
        track_id: int,
        lrclib_instance: str = "https://lrclib.net",
        *,
        download_mode: str = "prefer_synced",
        parent=None,
    ):
        super().__init__(parent)
        self.db_path = db_path
        self.track_id = track_id
        self.lrclib_instance = (lrclib_instance or "https://lrclib.net").rstrip("/")
        if not self.lrclib_instance.endswith("/api"):
            self.lrclib_instance += "/api"
        self.download_mode = (download_mode or "prefer_synced").strip() or "prefer_synced"

    def run(self):
        ok, msg, track_id, _ = download_track_lyrics(
            self.db_path,
            self.track_id,
            self.lrclib_instance,
            download_mode=self.download_mode,
            progress_callback=self.progress.emit,
        )
        self.finished.emit(ok, msg, track_id)
