from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from lyrics.providers.contracts import LyricsSearchResult
from ui.workers.lyrics_search_details_worker import LyricsSearchDetailsWorker


class LyricsSearchDetailsController(QObject):
    loaded = Signal(object, object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._token = 0
        self._workers: set[LyricsSearchDetailsWorker] = set()
        workers = self._workers

        def interrupt_workers():
            for worker in workers:
                worker.requestInterruption()

        self.destroyed.connect(interrupt_workers)

    def cancel(self) -> None:
        self._token += 1
        for worker in self._workers:
            worker.requestInterruption()

    def request(self, instance: str, result: LyricsSearchResult) -> None:
        self.cancel()
        if result.lyrics_loaded:
            self.loaded.emit(result, result, "")
            return
        worker = LyricsSearchDetailsWorker(instance, result, self._token)
        self._workers.add(worker)
        worker.completed.connect(self._on_completed)
        worker.finished.connect(self._on_finished)
        worker.start()

    def _on_completed(self, token: int, original, result, error: str) -> None:
        if token == self._token:
            self.loaded.emit(original, result, error)

    def _on_finished(self) -> None:
        self._workers.discard(self.sender())
