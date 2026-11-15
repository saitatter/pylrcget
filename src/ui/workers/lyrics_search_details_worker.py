from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QCoreApplication, QThread, Signal

from core.lrclib_client import LrcLibAPI
from lyrics.providers.contracts import LyricsSearchResult


class LyricsSearchDetailsWorker(QThread):
    completed = Signal(int, object, object, str)

    def __init__(self, instance: str, result: LyricsSearchResult, token: int):
        # Keep an in-flight HTTP request alive if its dialog is closed.
        super().__init__(QCoreApplication.instance())
        self.instance = instance
        self.result = result
        self.token = token
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)
        self.finished.connect(self.deleteLater)

    def stop(self) -> None:
        self.requestInterruption()
        self.wait()

    def run(self) -> None:
        try:
            if self.isInterruptionRequested():
                return
            if self.result.provider != "lrclib" or not self.result.provider_track_id:
                raise ValueError("Cannot load lyrics without a LRCLIB record ID")
            api = LrcLibAPI(self.instance, is_cancelled=self.isInterruptionRequested)
            lyrics = api.get_lyrics_by_id(self.result.provider_track_id)
            has_plain = bool((lyrics.plain_lyrics or "").strip())
            has_synced = bool((lyrics.synced_lyrics or "").strip())
            if not has_plain and not has_synced and not lyrics.instrumental:
                raise ValueError("Selected result no longer contains lyrics. Search again.")
            loaded = replace(
                self.result, plain_lyrics=lyrics.plain_lyrics, synced_lyrics=lyrics.synced_lyrics,
                instrumental=lyrics.instrumental, lyrics_loaded=True,
                has_plain_lyrics=has_plain, has_synced_lyrics=has_synced,
            )
            if not self.isInterruptionRequested():
                self.completed.emit(self.token, self.result, loaded, "")
        except Exception as exc:  # noqa: BLE001
            if not self.isInterruptionRequested():
                self.completed.emit(self.token, self.result, None, str(exc))
