from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import sqlite3
from typing import Callable

from PySide6.QtCore import QObject, QTimer

from core.utils import plain_text_from_lrc
from db.models import Track
from db.queries import (
    get_config,
    get_track_by_id,
    get_track_ids_for_download_mode,
    record_download_history_batch,
    update_track_plain_lyrics,
    update_track_synced_lyrics,
)
from core.tracklist_models import DownloadState
from ui.dialogs.batch_lyrics_match_dialog import BatchLyricsMatchDialog
from ui.services.feedback import notify_user
from ui.services.download_modes import download_mode_label, no_missing_tracks_message
from ui.services.lyrics_match_retry import LyricsMatchCandidate
from ui.services.lyrics_download_service import sync_track_outputs_with_result
from ui.widgets.download_progress_overlay import DownloadProgressOverlay
from ui.workers.bulk_lyrics_download_worker import BulkDownloadStats, BulkLyricsDownloadWorker
from ui.workers.lyrics_retry_search_worker import LyricsRetrySearchWorker

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
        self._failed_download_track_ids: list[int] = []
        self._retry_search_worker: LyricsRetrySearchWorker | None = None

        retry_failed_signal = getattr(self._overlay, "retryFailedRequested", None)
        if retry_failed_signal is not None:
            retry_failed_signal.connect(self._retry_failed_downloads_with_search)

    def start_downloads(self, track_ids: list[int], *, mode_override: str = "use_global") -> None:
        request = self._build_request(track_ids, mode_override=mode_override)
        if request is None:
            return

        for track_id in request.track_ids:
            self._set_track_download_state(track_id, DownloadState.LOADING)
        self._active_request = request
        self._active_track_ids = set(request.track_ids)
        self._pending_history_entries = []
        self._failed_download_track_ids = []

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
        if self._download_worker is not None and self._download_worker.isRunning():
            self._download_worker.requestInterruption()
        if self._retry_search_worker is not None and self._retry_search_worker.isRunning():
            self._retry_search_worker.requestInterruption()

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
        self._active_track_ids.discard(int(track_id))
        # In batch mode a successful item means "candidate found"; no lyrics are written until
        # the review dialog is committed explicitly by the user.
        state = DownloadState.LOADING if ok else DownloadState.ERROR
        self._set_track_download_state(int(track_id), state)
        if not ok:
            failed_id = int(track_id)
            if failed_id not in self._failed_download_track_ids:
                self._failed_download_track_ids.append(failed_id)
        self._overlay.append_result(track_label, msg, ok)
        if not ok:
            history_entry = self._build_download_history_entry(int(track_id), track_label, msg)
            if history_entry is not None:
                self._pending_history_entries.append(history_entry)

        token = self._state_tokens.get(int(track_id), 0) + 1
        self._state_tokens[int(track_id)] = token
        if not ok:
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
        except (AttributeError, RuntimeError) as exc:
            logger.warning("Failed to refresh current view after lyrics download: %s", exc)
        try:
            self._refresh_history()
        except (sqlite3.Error, AttributeError) as exc:
            logger.warning("Failed to refresh history after lyrics download: %s", exc)

        stats_dict: BulkDownloadStats = {
            "total": int(stats.get("total", 0)) if isinstance(stats, dict) else 0,
            "ok": int(stats.get("ok", 0)) if isinstance(stats, dict) else 0,
            "failed": int(stats.get("failed", 0)) if isinstance(stats, dict) else 0,
            "cancelled": bool(stats.get("cancelled")) if isinstance(stats, dict) else False,
        }
        self._overlay.finish_batch(msg, cancelled=bool(stats_dict.get("cancelled")))
        candidates = [
            candidate
            for candidate in (stats.get("candidates", []) if isinstance(stats, dict) else [])
            if isinstance(candidate, LyricsMatchCandidate)
        ]
        show_retry_failed = getattr(self._overlay, "show_retry_failed", None)
        if callable(show_retry_failed):
            retry_count = 0 if stats_dict.get("cancelled") else len(self._failed_download_track_ids)
            show_retry_failed(retry_count)
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
        elif candidates:
            notify_user(
                self._app_state,
                f"Review {len(candidates)} lyrics match candidate(s) before applying.",
                "info",
                show_status=self._show_status,
                status_timeout_ms=4000,
            )
            self._review_retry_candidates(candidates, context="download")
        else:
            notify_user(
                self._app_state,
                "Lyrics search completed. No matches found.",
                "success",
            )
            queue_auto_close = getattr(self._overlay, "queue_auto_close", None)
            if callable(queue_auto_close):
                queue_auto_close(2200)
        self._download_worker = None
        self._active_request = None

    def _retry_failed_downloads_with_search(self) -> None:
        failed_ids = list(dict.fromkeys(self._failed_download_track_ids))
        if not failed_ids:
            return
        if self._retry_search_worker is not None and self._retry_search_worker.isRunning():
            return
        config = get_config(self._app_state.db)
        lrclib_instance = self._normalize_lrclib_base(config.lrclib_instance or "https://lrclib.net")

        self._overlay.start_batch("Retry failed search", len(failed_ids))
        self._show_status("Searching LRCLIB with relaxed queries...", None)
        self._retry_search_worker = LyricsRetrySearchWorker(
            self._app_state.db_path,
            failed_ids,
            lrclib_instance,
            parent=self,
        )
        self._retry_search_worker.progress.connect(self._on_retry_search_progress)
        self._retry_search_worker.finishedSearch.connect(self._on_retry_search_finished)
        self._retry_search_worker.start()

    def _on_retry_search_progress(self, current: int, total: int, track_label: str, status: str) -> None:
        self._overlay.update_progress(current, total, track_label, status)
        self._show_status(status, None)

    def _on_retry_search_finished(self, candidates: list, error: str) -> None:
        self._retry_search_worker = None
        if error:
            msg = f"Relaxed lyrics search failed: {error}"
            self._overlay.finish_batch(msg)
            notify_user(self._app_state, msg, "error", show_status=self._show_status, status_timeout_ms=4500)
            return

        if not candidates:
            msg = "Relaxed lyrics search finished. No candidate matches found."
            self._overlay.finish_batch(msg)
            notify_user(self._app_state, msg, "warning", show_status=self._show_status, status_timeout_ms=4500)
            return

        self._overlay.finish_batch(f"Relaxed lyrics search found {len(candidates)} candidate match(es).")
        self._review_retry_candidates([candidate for candidate in candidates if isinstance(candidate, LyricsMatchCandidate)])

    def _review_retry_candidates(self, candidates: list[LyricsMatchCandidate], *, context: str = "retry") -> None:
        dialog = BatchLyricsMatchDialog(candidates, parent=self.parent())
        if not dialog.exec():
            for candidate in candidates:
                self._set_track_download_state(int(candidate.track_id), DownloadState.IDLE)
            return
        selected = dialog.selected_candidates()
        if not selected:
            for candidate in candidates:
                self._set_track_download_state(int(candidate.track_id), DownloadState.IDLE)
            notify_user(
                self._app_state,
                "No lyrics matches were selected.",
                "info",
                show_status=self._show_status,
                status_timeout_ms=3000,
            )
            return

        applied_count = 0
        for candidate in selected:
            if self._apply_retry_candidate(candidate):
                applied_count += 1

        if not applied_count:
            return
        self._flush_pending_download_history()
        self._refresh_visible_library_view()
        self._refresh_history()
        label = "downloaded" if context == "download" else "failed"
        notify_user(
            self._app_state,
            f"Applied lyrics to {applied_count} {label} track{'s' if applied_count != 1 else ''}.",
            "success",
            show_status=self._show_status,
            status_timeout_ms=3500,
        )

    def _apply_retry_candidate(self, candidate: LyricsMatchCandidate) -> bool:
        try:
            track = get_track_by_id(self._app_state.db, int(candidate.track_id))
        except (sqlite3.Error, AttributeError, TypeError) as exc:
            logger.warning("Failed to load track for lyrics retry candidate %s: %s", candidate.track_id, exc)
            return False

        updated = self._apply_selected_lyrics(candidate.track_id, candidate.plain_lyrics, candidate.synced_lyrics)
        if updated is None:
            return False

        score_note = f" Match: {int(candidate.score)}%."
        message = (
            f"Downloaded synced lyrics via reviewed match.{score_note}"
            if updated.lrc_lyrics
            else f"Downloaded plain lyrics via reviewed match.{score_note}"
        )
        history_entry = self._build_download_history_entry(
            int(candidate.track_id),
            f"{track.artist_name or ''} - {track.title or ''}".strip(" -"),
            message,
        )
        if history_entry is not None:
            self._pending_history_entries.append(history_entry)

        self._set_track_download_state(int(candidate.track_id), DownloadState.SUCCESS)
        if self._current_player_track_id() == int(candidate.track_id):
            self._set_track_lyrics_views(updated)
        return True

    def _apply_selected_lyrics(self, track_id: int, plain: str, synced: str) -> Track | None:
        synced_text = (synced or "").strip()
        plain_text = (plain or "").strip()
        if synced_text:
            if not plain_text:
                plain_text = plain_text_from_lrc(synced_text)
            track = update_track_synced_lyrics(self._app_state.db, int(track_id), synced_text, plain_text)
        elif plain_text:
            track = update_track_plain_lyrics(self._app_state.db, int(track_id), plain_text)
        else:
            return None

        config = get_config(self._app_state.db)
        sync_track_outputs_with_result(track, config)
        return track

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
        except (sqlite3.Error, AttributeError, TypeError):
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
        except (sqlite3.Error, AttributeError) as exc:
            logger.warning("Failed to record batch download history: %s", exc)
        finally:
            self._pending_history_entries = []

    @staticmethod
    def _download_mode_label(mode: str) -> str:
        return download_mode_label(mode)
