from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject

from ui.services.lyrics_cleanup_service import LyricsCleanupOptions
from ui.workers.lyrics_cleanup_worker import LyricsCleanupWorker


class LyricsCleanupController(QObject):
    def __init__(self, app_state, *, show_status: Callable[[str, int | None], None], parent=None) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._show_status = show_status
        self._worker: LyricsCleanupWorker | None = None

    def cleanup(
        self,
        track_ids: list[int],
        options: LyricsCleanupOptions,
        *,
        on_item_finished: Callable[[int, dict], None] | None = None,
        on_finished: Callable[[bool, str, dict], None] | None = None,
    ) -> bool:
        ids = list(dict.fromkeys(int(track_id) for track_id in track_ids if track_id is not None))
        if not ids or (self._worker is not None and self._worker.isRunning()):
            return False

        self._worker = LyricsCleanupWorker(self._app_state.db_path, ids, options, parent=self)

        def handle_item(track_id: int, payload: object) -> None:
            if on_item_finished is not None:
                on_item_finished(int(track_id), dict(payload or {}))

        def handle_finished(ok: bool, summary: str, stats: dict) -> None:
            worker = self._worker
            self._worker = None
            if worker is not None:
                worker.deleteLater()
            if on_finished is not None:
                on_finished(bool(ok), summary, stats)

        self._worker.itemFinished.connect(handle_item)
        self._worker.finishedCleanup.connect(handle_finished)
        self._show_status(f"Cleaning lyrics for {len(ids)} track(s)...", 2500)
        self._worker.start()
        return True

    def cancel(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.requestInterruption()
