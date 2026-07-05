from __future__ import annotations

from collections.abc import Callable
import logging
import sqlite3

from PySide6.QtCore import QObject

from db.queries import get_track_by_id
from ui.workers.track_output_sync_worker import TrackOutputSyncWorker

logger = logging.getLogger(__name__)


class LyricsOutputController(QObject):
    def __init__(
        self,
        app_state,
        *,
        show_status: Callable[[str, int | None], None],
        lyrics_views: Callable[[], list],
        on_track_synced: Callable[[int, dict], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._show_status = show_status
        self._lyrics_views = lyrics_views
        self._on_track_synced = on_track_synced
        self._worker: TrackOutputSyncWorker | None = None

    def sync_tracks(
        self,
        track_ids: list[int],
        *,
        on_item_finished: Callable[[int, dict], None] | None = None,
        on_finished: Callable[[bool, str, dict], None] | None = None,
    ) -> bool:
        track_ids = [int(track_id) for track_id in track_ids if track_id is not None]
        if not track_ids:
            return False
        if self._worker is not None and self._worker.isRunning():
            return False

        self._worker = TrackOutputSyncWorker(self._app_state.db_path, track_ids, parent=self)

        def _handle_item_finished(track_id: int, payload: dict) -> None:
            if on_item_finished is not None:
                on_item_finished(int(track_id), payload)
            if self._on_track_synced is not None:
                self._on_track_synced(int(track_id), payload)

        def _handle_finished(ok: bool, summary: str, stats: dict) -> None:
            worker = self._worker
            self._worker = None
            if worker is not None:
                worker.deleteLater()
            if on_finished is not None:
                on_finished(bool(ok), summary, stats)

        self._worker.itemFinished.connect(_handle_item_finished)
        self._worker.finishedSync.connect(_handle_finished)
        self._show_status(f"Syncing lyrics outputs for {len(track_ids)} track(s)...", 2500)
        self._worker.start()
        return True

    def cancel(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.requestInterruption()
