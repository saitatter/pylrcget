from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Callable

from PySide6.QtCore import QObject, QTimer

from db.database import get_config, get_track_by_id
from db.queries import get_track_ids_for_download_mode
from ui.widgets.download_progress_overlay import DownloadProgressOverlay
from ui.workers.bulk_lyrics_download_worker import BulkLyricsDownloadWorker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LyricsDownloadRequest:
    track_ids: tuple[int, ...]
    mode: str
    lrclib_instance: str


class LyricsDownloadController(QObject):
    def __init__(
        self,
        app_state,
        overlay: DownloadProgressOverlay,
        *,
        normalize_lrclib_base: Callable[[str], str],
        show_status: Callable[[str, int | None], None],
        current_player_track_id: Callable[[], int | None],
        set_track_lyrics_views: Callable[[object], None],
        refresh_visible_library_view: Callable[[], None],
        set_track_download_state: Callable[[int, str], None],
        get_track_download_state: Callable[[int], str],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._overlay = overlay
        self._normalize_lrclib_base = normalize_lrclib_base
        self._show_status = show_status
        self._current_player_track_id = current_player_track_id
        self._set_track_lyrics_views = set_track_lyrics_views
        self._refresh_visible_library_view = refresh_visible_library_view
        self._set_track_download_state = set_track_download_state
        self._get_track_download_state = get_track_download_state

        self._download_worker: BulkLyricsDownloadWorker | None = None
        self._active_track_ids: set[int] = set()
        self._state_tokens: dict[int, int] = {}

    def start_downloads(self, track_ids: list[int], *, mode_override: str = "use_global") -> None:
        request = self._build_request(track_ids, mode_override=mode_override)
        if request is None:
            return

        for track_id in request.track_ids:
            self._set_track_download_state(track_id, "loading")
        self._active_track_ids = set(request.track_ids)

        self._overlay.start_batch(self._download_mode_label(request.mode), len(request.track_ids))
        self._show_status(f"Starting lyrics download... ({request.lrclib_instance})", None)

        self._download_worker = BulkLyricsDownloadWorker(
            db_path=self._app_state.db_path,
            track_ids=list(request.track_ids),
            lrclib_instance=request.lrclib_instance,
            download_mode=request.mode,
            parent=self,
        )
        self._download_worker.progress.connect(self._on_download_progress)
        self._download_worker.itemFinished.connect(self._on_download_item_finished)
        self._download_worker.finishedBatch.connect(self._on_download_batch_finished)
        self._download_worker.start()

    def download_missing(self) -> None:
        mode = self._resolve_download_mode("use_global")
        track_ids = get_track_ids_for_download_mode(self._app_state.db, mode)
        if not track_ids:
            self._app_state.notify("No tracks are missing lyrics for the current download mode.", "info")
            return
        self.start_downloads(track_ids, mode_override=mode)

    def cancel(self) -> None:
        if self._download_worker is None or not self._download_worker.isRunning():
            return
        self._download_worker.requestInterruption()

    def _resolve_download_mode(self, mode_override: str = "use_global") -> str:
        if mode_override and mode_override != "use_global":
            return mode_override
        config = get_config(self._app_state.db)
        return str(config.download_lyrics_mode or "prefer_synced")

    def _build_request(self, track_ids: list[int], *, mode_override: str) -> LyricsDownloadRequest | None:
        unique_ids = tuple(dict.fromkeys(int(x) for x in track_ids if x is not None))
        if not unique_ids:
            self._app_state.notify("No tracks selected for lyrics download.", "warning")
            return None
        if self._download_worker is not None and self._download_worker.isRunning():
            self._app_state.notify("A lyrics download is already running.", "warning")
            return None

        config = get_config(self._app_state.db)
        return LyricsDownloadRequest(
            track_ids=unique_ids,
            mode=self._resolve_download_mode(mode_override),
            lrclib_instance=self._normalize_lrclib_base(config.lrclib_instance or "https://lrclib.net"),
        )

    def _on_download_progress(self, current: int, total: int, track_label: str, status: str, elapsed_s: float) -> None:
        del elapsed_s
        label = track_label or "Lyrics download"
        self._overlay.update_progress(current, total, label, status)
        self._show_status(status, None)

    def _on_download_item_finished(self, track_id: int, ok: bool, track_label: str, msg: str) -> None:
        try:
            current_track_id = self._current_player_track_id()
            if current_track_id is not None and current_track_id == int(track_id):
                track = get_track_by_id(self._app_state.db, int(track_id))
                self._set_track_lyrics_views(track)
        except Exception as exc:
            logger.warning("Failed to update track after lyrics download for %s: %s", track_id, exc)

        self._active_track_ids.discard(int(track_id))
        state = "success" if ok else "error"
        self._set_track_download_state(int(track_id), state)
        self._overlay.append_result(track_label, msg, ok)

        token = self._state_tokens.get(int(track_id), 0) + 1
        self._state_tokens[int(track_id)] = token
        QTimer.singleShot(
            1800,
            self,
            lambda tid=track_id, expected=token, expected_state=state: self._reset_track_download_state_if_unchanged(
                tid,
                expected,
                expected_state,
            ),
        )

    def _on_download_batch_finished(self, ok: bool, msg: str, stats: object) -> None:
        del ok
        self._show_status(msg, 4000)
        for track_id in list(self._active_track_ids):
            self._set_track_download_state(int(track_id), "idle")
        self._active_track_ids.clear()

        try:
            self._refresh_visible_library_view()
        except Exception as exc:
            logger.warning("Failed to refresh current view after lyrics download: %s", exc)

        stats_dict = stats if isinstance(stats, dict) else {}
        self._overlay.finish_batch(msg, cancelled=bool(stats_dict.get("cancelled")))
        if stats_dict.get("cancelled"):
            self._app_state.notify("Lyrics download cancelled.", "warning")
        elif int(stats_dict.get("failed", 0)) > 0 and int(stats_dict.get("ok", 0)) > 0:
            self._app_state.notify(msg, "warning")
        elif int(stats_dict.get("failed", 0)) > 0:
            self._app_state.notify(msg, "error")
        else:
            self._app_state.notify("Lyrics downloaded successfully.", "success")
        self._download_worker = None

    def _reset_track_download_state_if_unchanged(
        self,
        track_id: int,
        expected_token: int,
        expected_state: str,
    ) -> None:
        if self._state_tokens.get(int(track_id)) != int(expected_token):
            return
        if self._get_track_download_state(int(track_id)) != expected_state:
            return
        self._set_track_download_state(int(track_id), "idle")

    @staticmethod
    def _download_mode_label(mode: str) -> str:
        labels = {
            "prefer_synced": "Prefer synced",
            "synced_only": "Synced only",
            "plain_only": "Plain only",
        }
        return labels.get((mode or "").strip(), "Custom")
