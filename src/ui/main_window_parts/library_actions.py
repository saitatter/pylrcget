from __future__ import annotations

import logging
import os
import sqlite3

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from db.queries import (
    get_config,
    get_directories,
    get_track_by_id,
    mark_tracks_instrumental,
    unmark_tracks_instrumental,
)
from ui.constants import FEEDBACK_RESET_MS
from ui.services.feedback import exception_message, log_and_notify, notify_user
from ui.workers.library_scanner import LibraryScanner
from ui.workers.track_refresh_worker import TrackRefreshWorker

logger = logging.getLogger(__name__)


def refresh_library(window) -> None:
    if window.scanner is not None and window.scanner.isRunning():
        return
    directories = get_directories(window.app_state.db)
    if not directories:
        notify_user(
            window.app_state,
            "Add at least one music folder before starting a library scan.",
            "warning",
            show_status=window._show_status_message,
            status_timeout_ms=3000,
        )
        window.top_bar.set_button_feedback(window.top_bar.btn_refresh, "error")
        QTimer.singleShot(FEEDBACK_RESET_MS, window._reset_refresh_feedback)
        return

    logger.info("Starting library scan across %d folder(s).", len(directories))

    window.scan_row.setVisible(False)
    window.top_bar.set_actions_label("Scanning Library")
    window.top_bar.set_button_feedback(window.top_bar.btn_refresh, "loading")
    window.scan_overlay.start_batch(f"{len(directories)} folder(s)", 0)
    window.scan_overlay.update_progress(0, 0, "Library scan", "Discovering audio files...")
    window.btn_cancel_scan.setEnabled(True)

    config = get_config(window.app_state.db)
    logger.debug(
        "Library scan config: lyrics source mode=%s, worker count=%s",
        getattr(config, "scan_lyrics_source_mode", "both"),
        getattr(config, "scan_worker_count", 4),
    )
    window.scanner = LibraryScanner(
        window.app_state.db_path,
        directories,
        excluded_paths=config.scan_excluded_paths,
        excluded_patterns=config.scan_excluded_patterns,
        lyrics_lookup_subdir=config.lyrics_lookup_subdir,
        scan_lyrics_source_mode=getattr(config, "scan_lyrics_source_mode", "both"),
        lyrics_file_pattern=config.lyrics_file_pattern,
        scan_worker_count=getattr(config, "scan_worker_count", 4),
    )
    window.scanner.progress_signal.connect(window._update_scan_progress)
    window.scanner.finished_signal.connect(window._scan_finished)
    window.scanner.start()
    window.top_bar.btn_refresh.setEnabled(False)
    window._show_status_message("Scanning library...")


def update_scan_progress(window, scanned: int, total: int, current_path: str, elapsed_s: float) -> None:
    total = max(int(total), 0)
    scanned = max(int(scanned), 0)
    current_name = os.path.basename(current_path) if current_path else ""
    elapsed_s = max(0.0, float(elapsed_s or 0.0))

    if total <= 0:
        window.progress_bar.setRange(0, 0)
        window.scan_label.setText("Scanning…")
        window.scan_details.setText("Discovering audio files…")
        window.scan_overlay.update_progress(0, 0, "Library scan", "Discovering audio files...")
        return

    if window.progress_bar.maximum() == 0:
        window.progress_bar.setRange(0, 100)

    percent = int((scanned / total) * 100)
    percent = max(0, min(100, percent))

    window.progress_bar.setValue(percent)
    window.scan_label.setText(f"Scanning… {scanned}/{total} ({percent}%)")
    window.scan_details.setText(
        f"Current file: {current_name or 'Preparing next file…'}  •  Elapsed: {elapsed_s:.1f}s"
    )
    window.scan_overlay.update_progress(
        scanned,
        total,
        current_name or "Library scan",
        f"{scanned}/{total} ({percent}%)  •  Elapsed: {elapsed_s:.1f}s",
    )


def scan_finished(window, ok: bool, msg: str) -> None:
    window.progress_bar.setRange(0, 100)
    window.progress_bar.setValue(0)
    window.scan_row.setVisible(False)
    window.btn_cancel_scan.setEnabled(False)
    window.scan_overlay.finish_batch(
        msg or ("Library scan finished." if ok else "Library scan failed."),
        cancelled=not ok and "cancel" in (msg or "").lower(),
    )
    window.scan_overlay.queue_auto_close(5000)

    if ok:
        window._apply_track_filters()
        if hasattr(window, "_validate_current_selected_track"):
            window._validate_current_selected_track()
        window.scan_overlay.append_result("Library scan", msg or "Library scan finished successfully.", True)
        notify_user(
            window.app_state,
            msg or "Library scan finished successfully.",
            "success",
            show_status=window._show_status_message,
            status_timeout_ms=4000,
        )
        window.top_bar.set_button_feedback(window.top_bar.btn_refresh, "success")
        logger.info("Library scan finished successfully: %s", msg or "ok")
    else:
        if "cancel" in (msg or "").lower():
            window.scan_overlay.append_result("Library scan", msg or "Library scan cancelled.", False)
            notify_user(
                window.app_state,
                msg,
                "warning",
                show_status=window._show_status_message,
                status_timeout_ms=4000,
            )
            window.top_bar.set_button_feedback(window.top_bar.btn_refresh, "idle")
            logger.warning("Library scan cancelled: %s", msg)
        else:
            window.scan_overlay.append_result("Library scan", msg or "Library scan failed.", False)
            log_and_notify(
                window.app_state,
                logger,
                logging.ERROR,
                f"Library scanning failed: {msg}",
                "error",
                show_status=window._show_status_message,
                status_timeout_ms=4000,
            )
            window.top_bar.set_button_feedback(window.top_bar.btn_refresh, "error")

    window.top_bar.btn_refresh.setEnabled(True)
    QTimer.singleShot(FEEDBACK_RESET_MS, window._reset_refresh_feedback)
    window.scanner = None


def cancel_scan(window) -> None:
    if not hasattr(window, "scanner") or window.scanner is None:
        return
    window.btn_cancel_scan.setEnabled(False)
    window.scan_details.setText("Cancelling scan after the current batch…")
    window.scan_overlay.update_progress(-1, 0, "Library scan", "Cancelling scan after the current batch...")
    logger.info("Cancellation requested for library scan.")
    window.scanner.requestInterruption()


def on_download_lyrics(window, track_id: int) -> None:
    window.downloads.start_downloads([int(track_id)], mode_override="use_global")


def on_bulk_download_requested(window, track_ids: list[int], mode: str) -> None:
    window.downloads.start_downloads(track_ids, mode_override=mode)


def download_missing_lyrics(window) -> None:
    window.downloads.download_missing()


def refresh_track(window, track_id: int) -> None:
    refresh_tracks(window, [int(track_id)])


def refresh_tracks(window, track_ids: list[int]) -> None:
    track_ids = [int(track_id) for track_id in track_ids if track_id is not None]
    if not track_ids:
        return

    worker = getattr(window, "_track_refresh_worker", None)
    if worker is not None and worker.isRunning():
        return

    selected_before = set(track_ids)
    active_track_list = window._active_track_list_widget()
    window._track_refresh_worker = TrackRefreshWorker(window.app_state.db_path, track_ids, parent=window)

    def _on_progress(current: int, total: int, label: str, status: str) -> None:
        del current, total, label
        window._show_status_message(status, 1500)

    def _on_finished(ok: bool, summary: str, stats: dict) -> None:
        del ok
        worker_obj = window._track_refresh_worker
        window._track_refresh_worker = None
        if worker_obj is not None:
            worker_obj.deleteLater()

        refreshed_ids = {int(track_id) for track_id in stats.get("refreshed", [])}
        removed_ids = {int(track_id) for track_id in stats.get("removed", [])}
        failed_ids = {int(track_id) for track_id in stats.get("failed", [])}

        window._refresh_visible_library_view_after_downloads()
        if active_track_list is not None:
            active_track_list.restore_selection(selected_before - removed_ids)

        current_track_id = window._current_player_track_id()
        if current_track_id in removed_ids:
            window._clear_current_player_track()
        elif current_track_id in refreshed_ids:
            try:
                refreshed = get_track_by_id(window.app_state.db, int(current_track_id))
                window._update_current_player_track_meta(refreshed)
                window._set_track_lyrics_views(refreshed)
            except (sqlite3.Error, AttributeError, TypeError) as exc:
                logger.warning("Failed to refresh active track after disk refresh: %s", exc)

        if removed_ids or failed_ids:
            message = summary
            notify_user(
                window.app_state,
                message,
                "warning",
                show_status=window._show_status_message,
                status_timeout_ms=4000,
            )
        else:
            window._show_status_message(summary, 2500)

    window._track_refresh_worker.progress.connect(_on_progress)
    window._track_refresh_worker.finishedRefresh.connect(_on_finished)
    window._show_status_message(f"Refreshing {len(track_ids)} track(s) from disk...", 2500)
    window._track_refresh_worker.start()


def set_track_download_state_all(window, track_id: int, state: str) -> None:
    window.track_list.set_download_state(int(track_id), state)
    window.albums_tab.set_download_state(int(track_id), state)
    window.artists_tab.set_download_state(int(track_id), state)


def get_primary_track_download_state(window, track_id: int) -> str:
    return window.track_list.get_download_state(int(track_id))


def confirm_bulk(window, title: str, text: str, count: int) -> bool:
    if count < 10:
        return True
    result = QMessageBox.question(
        window,
        title,
        f"{text}\n\nSelected: {count}",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    return result == QMessageBox.StandardButton.Yes


def on_mark_instrumental(window, track_ids: list[int], *, mark_tracks=mark_tracks_instrumental) -> None:
    track_ids = [int(value) for value in track_ids if value is not None]
    if not track_ids:
        return

    if not window._confirm_bulk("Instrumental", "Mark selected tracks as instrumental?", len(track_ids)):
        return

    selected_before = set(track_ids)
    active_track_list = window._active_track_list_widget()
    instrumental_filter_enabled = window.top_bar.filter_values()["instrumental"]

    try:
        mark_tracks(window.app_state.db, track_ids)
        window._refresh_visible_library_view_after_downloads()
        if active_track_list is not None:
            active_track_list.restore_selection(selected_before)
        message = f"Marked {len(track_ids)} track(s) as instrumental."
        if not instrumental_filter_enabled:
            message += " Enable the Instrumental filter to show them."
        window._show_status_message(message, 5000 if not instrumental_filter_enabled else 3000)
    except sqlite3.Error as exc:
        log_and_notify(
            window.app_state,
            logger,
            logging.ERROR,
            exception_message("Failed to mark tracks as instrumental", exc),
            "error",
            show_status=window._show_status_message,
            status_timeout_ms=4000,
        )
        return

    window._publish_instrumental_to_lrclib(track_ids)


def on_unmark_instrumental(window, track_ids: list[int], *, unmark_tracks=unmark_tracks_instrumental) -> None:
    track_ids = [int(value) for value in track_ids if value is not None]
    if not track_ids:
        return

    if not window._confirm_bulk("Instrumental", "Unmark instrumental for selected tracks?", len(track_ids)):
        return

    selected_before = set(track_ids)
    active_track_list = window._active_track_list_widget()

    try:
        unmark_tracks(window.app_state.db, track_ids)
        window._show_status_message(f"Unmarked {len(track_ids)} track(s).", 3000)
        window._refresh_visible_library_view_after_downloads()
        if active_track_list is not None:
            active_track_list.restore_selection(selected_before)
    except sqlite3.Error as exc:
        log_and_notify(
            window.app_state,
            logger,
            logging.ERROR,
            exception_message("Failed to update tracks", exc),
            "error",
            show_status=window._show_status_message,
            status_timeout_ms=4000,
        )


def publish_instrumental_to_lrclib(window, track_ids: list[int]) -> None:
    reply = QMessageBox.question(
        window,
        "Publish Instrumental",
        f"Also mark {len(track_ids)} track(s) as instrumental on LRCLIB?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if reply != QMessageBox.StandardButton.Yes:
        return

    from ui.workers.bulk_publish_instrumental_worker import BulkPublishInstrumentalWorker

    config = get_config(window.app_state.db)
    lrclib_url = window._normalize_lrclib_base(config.lrclib_instance)

    window._instrumental_worker = BulkPublishInstrumentalWorker(
        db_path=window.app_state.db_path,
        track_ids=track_ids,
        lrclib_instance=lrclib_url,
        parent=window,
    )

    def _on_finished(ok: bool, summary: str, stats: dict):
        window._instrumental_worker = None
        notify_user(
            window.app_state,
            summary,
            "success" if ok else "warning",
            show_status=window._show_status_message,
            status_timeout_ms=5000,
        )

    window._instrumental_worker.finished.connect(_on_finished)
    window._show_status_message(f"Publishing instrumental status for {len(track_ids)} track(s)...", 3000)
    window._instrumental_worker.start()