from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Callable

from PySide6.QtCore import QObject, QTimer

from db.models import Track
from db.queries import (
    get_config,
    get_track_by_id,
    get_track_ids_for_download_mode,
    record_download_history_batch,
)
from core.tracklist_models import DownloadState
from ui.services.feedback import notify_user
from ui.services.download_modes import download_mode_label, no_missing_tracks_message
from ui.widgets.download_progress_overlay import DownloadProgressOverlay
from ui.workers.bulk_lyrics_download_worker import BulkDownloadStats, BulkLyricsDownloadWorker

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
        set_track_lyrics_views: Callable[[Track], None],
        refresh_visible_library_view: Callable[[], None],
        refresh_history: Callable[[], None],
        set_track_download_state: Callable[[int, DownloadState], None],
        get_track_download_state: Callable[[int], DownloadState],
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
        self._refresh_history = refresh_history
        self._set_track_download_state = set_track_download_state
        self._get_track_download_state = get_track_download_state

        self._download_worker: BulkLyricsDownloadWorker | None = None
        self._active_request: LyricsDownloadRequest | None = None
        self._active_track_ids: set[int] = set()
        self._state_tokens: dict[int, int] = {}
        self._pending_history_entries: list[dict[str, object]] = []

    def start_downloads(self, track_ids: list[int], *, mode_override: str = "use_global") -> None:
        request = self._build_request(track_ids, mode_override=mode_override)
        if request is None:
            return

        for track_id in request.track_ids:
            self._set_track_download_state(track_id, DownloadState.LOADING)
        self._active_request = request
        self._active_track_ids = set(request.track_ids)
        self._pending_history_entries = []

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
            notify_user(
                self._app_state,
                no_missing_tracks_message(mode),
                "info",
                show_status=self._show_status,
                status_timeout_ms=4000,
            )
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
            notify_user(
                self._app_state,
                "No tracks selected for lyrics download.",
                "warning",
                show_status=self._show_status,
                status_timeout_ms=3000,
            )
            return None
        if self._download_worker is not None and self._download_worker.isRunning():
            notify_user(
                self._app_state,
                "A lyrics download is already running.",
                "warning",
                show_status=self._show_status,
                status_timeout_ms=3000,
            )
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
        state = DownloadState.SUCCESS if ok else DownloadState.ERROR
        self._set_track_download_state(int(track_id), state)
        self._overlay.append_result(track_label, msg, ok)
        history_entry = self._build_download_history_entry(int(track_id), track_label, msg)
        if history_entry is not None:
            self._pending_history_entries.append(history_entry)

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

    def _on_download_batch_finished(self, ok: bool, msg: str, stats: dict) -> None:
        del ok
        self._show_status(msg, 4000)
        for track_id in list(self._active_track_ids):
            self._set_track_download_state(int(track_id), DownloadState.IDLE)
        self._active_track_ids.clear()
        self._flush_pending_download_history()

        try:
            self._refresh_visible_library_view()
        except Exception as exc:
            logger.warning("Failed to refresh current view after lyrics download: %s", exc)
        try:
            self._refresh_history()
        except Exception as exc:
            logger.warning("Failed to refresh history after lyrics download: %s", exc)

        stats_dict: BulkDownloadStats = {
            "total": int(stats.get("total", 0)) if isinstance(stats, dict) else 0,
            "ok": int(stats.get("ok", 0)) if isinstance(stats, dict) else 0,
            "failed": int(stats.get("failed", 0)) if isinstance(stats, dict) else 0,
            "cancelled": bool(stats.get("cancelled")) if isinstance(stats, dict) else False,
        }
        self._overlay.finish_batch(msg, cancelled=bool(stats_dict.get("cancelled")))
        if stats_dict.get("cancelled"):
            notify_user(
                self._app_state,
                "Lyrics download cancelled.",
                "warning",
            )
        elif int(stats_dict.get("failed", 0)) > 0 and int(stats_dict.get("ok", 0)) > 0:
            notify_user(
                self._app_state,
                msg,
                "warning",
            )
        elif int(stats_dict.get("failed", 0)) > 0:
            notify_user(
                self._app_state,
                msg,
                "error",
            )
        else:
            notify_user(
                self._app_state,
                "Lyrics downloaded successfully.",
                "success",
            )
            queue_auto_close = getattr(self._overlay, "queue_auto_close", None)
            if callable(queue_auto_close):
                queue_auto_close(2200)
        self._download_worker = None
        self._active_request = None

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
        self._set_track_download_state(int(track_id), DownloadState.IDLE)

    def _build_download_history_entry(self, track_id: int, track_label: str, message: str) -> dict[str, object] | None:
        try:
            track = get_track_by_id(self._app_state.db, int(track_id))
            title = str(track.title or "").strip()
            artist_name = str(track.artist_name or "").strip()
            album_name = str(track.album_name or "").strip()
        except Exception:
            title = ""
            artist_name = ""
            album_name = ""

        label = (track_label or "").strip()
        if not title and label:
            parts = [part.strip() for part in label.split(" - ", 1)]
            if len(parts) == 2:
                artist_name = artist_name or parts[0]
                title = title or parts[1]
            else:
                title = label

        normalized_message = (message or "").strip()
        lowered = normalized_message.casefold()
        if "synced lyrics" in lowered:
            status = "synced"
        elif "plain lyrics" in lowered:
            status = "plain"
        elif "instrumental" in lowered:
            status = "instrumental"
        elif "does not exist" in lowered or "not found" in lowered:
            status = "not_found"
        else:
            status = "error"

        request = self._active_request
        lrclib_instance = request.lrclib_instance if request is not None else ""
        mode = request.mode if request is not None else self._resolve_download_mode("use_global")

        return {
            "track_id": int(track_id),
            "title": title,
            "artist_name": artist_name,
            "album_name": album_name,
            "download_mode": mode,
            "download_status": status,
            "message": normalized_message,
            "lrclib_instance": lrclib_instance,
            "downloaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }

    def _flush_pending_download_history(self) -> None:
        if not self._pending_history_entries:
            return
        try:
            record_download_history_batch(self._app_state.db, self._pending_history_entries)
        except Exception as exc:
            logger.warning("Failed to record batch download history: %s", exc)
        finally:
            self._pending_history_entries = []

    @staticmethod
    def _download_mode_label(mode: str) -> str:
        return download_mode_label(mode)
