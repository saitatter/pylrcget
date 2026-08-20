from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox

from db.queries import get_config, mark_tracks_instrumental, unmark_tracks_instrumental
from ui.services.feedback import exception_message, log_and_notify, notify_user

logger = logging.getLogger(__name__)


class TrackMaintenanceController(QObject):
    def __init__(
        self,
        app_state,
        *,
        window,
        confirm_bulk: Callable[[str, str, int], bool],
        active_track_list_widget: Callable[[], object | None],
        refresh_visible_library_view: Callable[[], None],
        show_status: Callable[[str, int | None], None],
        normalize_lrclib_base: Callable[[str], str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._window = window
        self._confirm_bulk = confirm_bulk
        self._active_track_list_widget = active_track_list_widget
        self._refresh_visible_library_view = refresh_visible_library_view
        self._show_status = show_status
        self._normalize_lrclib_base = normalize_lrclib_base
        self._instrumental_worker = None

    def mark_instrumental(self, track_ids: list[int]) -> None:
        track_ids = [int(value) for value in track_ids if value is not None]
        if not track_ids:
            return

        if not self._confirm_bulk("Instrumental", "Mark selected tracks as instrumental?", len(track_ids)):
            return

        selected_before = set(track_ids)
        active_track_list = self._active_track_list_widget()
        instrumental_filter_enabled = self._window.top_bar.filter_values()["instrumental"]

        try:
            mark_tracks_instrumental(self._app_state.db, track_ids)
            self._refresh_visible_library_view()
            if active_track_list is not None:
                active_track_list.restore_selection(selected_before)
            message = f"Marked {len(track_ids)} track(s) as instrumental."
            if not instrumental_filter_enabled:
                message += " Enable the Instrumental filter to show them."
            self._show_status(message, 5000 if not instrumental_filter_enabled else 3000)
        except sqlite3.Error as exc:
            log_and_notify(
                self._app_state,
                logger,
                logging.ERROR,
                exception_message("Failed to mark tracks as instrumental", exc),
                "error",
                show_status=self._show_status,
                status_timeout_ms=4000,
            )
            return

        self.publish_instrumental(track_ids)

    def unmark_instrumental(self, track_ids: list[int]) -> None:
        track_ids = [int(value) for value in track_ids if value is not None]
        if not track_ids:
            return

        if not self._confirm_bulk("Instrumental", "Unmark instrumental for selected tracks?", len(track_ids)):
            return

        selected_before = set(track_ids)
        active_track_list = self._active_track_list_widget()

        try:
            unmark_tracks_instrumental(self._app_state.db, track_ids)
            self._show_status(f"Unmarked {len(track_ids)} track(s).", 3000)
            self._refresh_visible_library_view()
            if active_track_list is not None:
                active_track_list.restore_selection(selected_before)
        except sqlite3.Error as exc:
            log_and_notify(
                self._app_state,
                logger,
                logging.ERROR,
                exception_message("Failed to update tracks", exc),
                "error",
                show_status=self._show_status,
                status_timeout_ms=4000,
            )

    def publish_instrumental(self, track_ids: list[int]) -> None:
        track_ids = [int(value) for value in track_ids if value is not None]
        if not track_ids:
            return

        reply = QMessageBox.question(
            self._window,
            "Publish Instrumental",
            f"Also mark {len(track_ids)} track(s) as instrumental on LRCLIB?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from ui.workers.bulk_publish_instrumental_worker import (
            BulkPublishInstrumentalWorker,
        )

        config = get_config(self._app_state.db)
        lrclib_url = self._normalize_lrclib_base(config.lrclib_instance)

        self._instrumental_worker = BulkPublishInstrumentalWorker(
            db_path=self._app_state.db_path,
            track_ids=track_ids,
            lrclib_instance=lrclib_url,
            parent=self,
        )

        def _on_finished(ok: bool, summary: str, stats: dict):
            del stats
            self._instrumental_worker = None
            notify_user(
                self._app_state,
                summary,
                "success" if ok else "warning",
                show_status=self._show_status,
                status_timeout_ms=5000,
            )

        self._instrumental_worker.finished.connect(_on_finished)
        self._show_status(f"Publishing instrumental status for {len(track_ids)} track(s)...", 3000)
        self._instrumental_worker.start()
