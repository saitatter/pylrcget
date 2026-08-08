from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import replace

from PySide6.QtWidgets import QDialog

from core.tracklist_models import LyricsState
from core.utils import ms_to_ts as _ms_to_ts, parse_lrc
from db.queries import (
    clear_track_dirty_lyrics,
    get_config,
    get_similar_lyrics_track_rows,
    get_track_by_id,
    update_track_dirty_lyrics,
    update_track_null_lyrics,
    update_track_plain_lyrics,
    update_track_synced_lyrics,
)
from ui.services.feedback import exception_message, log_and_notify, notify_user
from ui.services.lyrics_download_service import sync_track_outputs_with_result

logger = logging.getLogger(__name__)


def canonical_lyrics_pair(lrc: str | None, txt: str | None) -> tuple[str, str]:
    lrc_text = (lrc or "").strip()
    txt_text = (txt or "").strip()
    if not lrc_text:
        return "", txt_text

    pairs = parse_lrc(lrc_text)
    if not pairs:
        return lrc_text, txt_text

    pairs.sort(key=lambda item: item[0])
    canonical_lrc = "\n".join(
        f"[{_ms_to_ts(ms)}] {text.strip()}" if text.strip() else f"[{_ms_to_ts(ms)}]"
        for ms, text in pairs
    ).strip()
    canonical_txt = txt_text or "\n".join(text.rstrip() for _ms, text in pairs).rstrip()
    return canonical_lrc, canonical_txt


def lyrics_state_from_track(track) -> LyricsState:
    if track.instrumental or track.lrc_lyrics == "[au: instrumental]":
        return LyricsState.INSTRUMENTAL
    if track.lrc_lyrics:
        return LyricsState.SYNCED
    if track.txt_lyrics:
        return LyricsState.PLAIN
    return LyricsState.NONE


def update_single_track_lyrics_state(window, track) -> None:
    state = lyrics_state_from_track(track)
    track_id = int(track.id)
    window.track_list.update_track_lyrics_state(track_id, state)
    window.albums_tab.update_track_lyrics_state(track_id, state)
    window.artists_tab.update_track_lyrics_state(track_id, state)
    window.album_artists_tab.update_track_lyrics_state(track_id, state)


def on_lyrics_save_requested(window, lrc: str, txt: str) -> None:
    track_id = window._editing_track_id
    if track_id is None:
        notify_user(
            window.app_state,
            "Select a track first.",
            "warning",
            show_status=window._show_status_message,
            status_timeout_ms=3000,
        )
        for view in window._all_lyrics_views():
            view.set_save_feedback("error", "No Track")
        return

    for view in window._all_lyrics_views():
        view.set_save_feedback("loading", "Saving...")
    try:
        if lrc.strip():
            update_track_synced_lyrics(window.app_state.db, track_id, lrc.strip(), (txt or "").strip())
        elif (txt or "").strip():
            update_track_plain_lyrics(window.app_state.db, track_id, (txt or "").strip())
        else:
            update_track_null_lyrics(window.app_state.db, track_id)

        track = get_track_by_id(window.app_state.db, track_id)
        window._editing_saved_lyrics = canonical_lyrics_pair(track.lrc_lyrics, track.txt_lyrics)
        window._set_track_lyrics_views(track)
        window._mark_track_lyrics_clean(track)
        window._update_single_track_lyrics_state(track)
        window._show_status_message("Lyrics saved.", 2500)
        window.toasts.show_toast("Lyrics saved.", "success")
        for view in window._all_lyrics_views():
            view.set_save_feedback("success", "Saved")
        if not window._sync_track_lyrics_outputs(track):
            window._show_status_message("Lyrics output sync is already running.", 3000)
    except (sqlite3.Error, OSError, ValueError) as exc:
        log_and_notify(
            window.app_state,
            logger,
            logging.ERROR,
            exception_message("Failed to save lyrics", exc),
            "error",
            show_status=window._show_status_message,
            status_timeout_ms=4000,
        )
        for view in window._all_lyrics_views():
            view.set_save_feedback("error", "Save Failed")


def on_propagate_lyrics_requested(window, lrc: str, txt: str) -> None:
    source_track_id = window._editing_track_id
    if source_track_id is None:
        notify_user(
            window.app_state,
            "Select a track before syncing lyrics to similar tracks.",
            "warning",
            show_status=window._show_status_message,
            status_timeout_ms=3000,
        )
        for view in window._all_lyrics_views():
            view.set_sync_others_feedback("error", "No Track")
        return

    lrc_text, txt_text = canonical_lyrics_pair(lrc, txt)
    if not lrc_text and not txt_text:
        notify_user(
            window.app_state,
            "No lyrics are available to sync from this track.",
            "warning",
            show_status=window._show_status_message,
            status_timeout_ms=3000,
        )
        for view in window._all_lyrics_views():
            view.set_sync_others_feedback("error", "No Lyrics")
        return

    try:
        matches = get_similar_lyrics_track_rows(window.app_state.db, int(source_track_id))
    except sqlite3.Error as exc:
        log_and_notify(
            window.app_state,
            logger,
            logging.ERROR,
            exception_message("Failed to find similar tracks", exc),
            "error",
            show_status=window._show_status_message,
            status_timeout_ms=4000,
        )
        for view in window._all_lyrics_views():
            view.set_sync_others_feedback("error", "Search Failed")
        return

    if not matches:
        notify_user(
            window.app_state,
            "No similar tracks were found for this title, artist, and duration.",
            "warning",
            show_status=window._show_status_message,
            status_timeout_ms=3500,
        )
        for view in window._all_lyrics_views():
            view.set_sync_others_feedback("error", "No Matches")
        return

    from ui.dialogs.lyrics_propagate_dialog import LyricsPropagateDialog

    dialog = LyricsPropagateDialog(matches, source_lyrics=lrc_text or txt_text, parent=window)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    target_ids = dialog.selected_track_ids()
    if not target_ids:
        notify_user(
            window.app_state,
            "No tracks were checked for syncing.",
            "warning",
            show_status=window._show_status_message,
            status_timeout_ms=3000,
        )
        for view in window._all_lyrics_views():
            view.set_sync_others_feedback("error", "None Checked")
        return

    for view in window._all_lyrics_views():
        view.set_sync_others_feedback("loading", "Syncing...")

    try:
        if window._dirty_lyrics_timer.isActive():
            window._dirty_lyrics_timer.stop()

        applied_ids = [int(source_track_id), *[int(track_id) for track_id in target_ids]]
        output_errors: list[str] = []
        synced_track_ids: list[int] = []
        for track_id in applied_ids:
            track = window._save_lyrics_text_to_track(track_id, lrc_text, txt_text)
            window._mark_track_lyrics_clean(track)
            window._update_single_track_lyrics_state(track)
            synced_track_ids.append(int(track.id))

        source_track = get_track_by_id(window.app_state.db, int(source_track_id))
        window._editing_saved_lyrics = canonical_lyrics_pair(source_track.lrc_lyrics, source_track.txt_lyrics)
        window._set_track_lyrics_views(source_track)

        if not window.lyrics_output.sync_tracks(
            synced_track_ids,
            on_item_finished=window._on_track_lyrics_output_synced,
            on_finished=window._on_track_lyrics_output_sync_finished,
        ):
            output_errors.append("Lyrics output sync is already running.")

        synced_count = len(target_ids)
        message = f"Lyrics synced to {synced_count} similar track(s)."
        notify_type = "warning" if output_errors else "success"
        notify_user(
            window.app_state,
            message if not output_errors else f"{message} Some output sync steps failed.",
            notify_type,
            show_status=window._show_status_message,
            status_timeout_ms=4000,
        )
        for error in output_errors[:3]:
            logger.warning("Lyrics propagation output sync issue: %s", error)
        for view in window._all_lyrics_views():
            view.set_sync_others_feedback("success", "Synced")
    except (sqlite3.Error, OSError, ValueError) as exc:
        log_and_notify(
            window.app_state,
            logger,
            logging.ERROR,
            exception_message("Failed to sync lyrics to similar tracks", exc),
            "error",
            show_status=window._show_status_message,
            status_timeout_ms=4000,
        )
        for view in window._all_lyrics_views():
            view.set_sync_others_feedback("error", "Sync Failed")


def save_lyrics_text_to_track(window, track_id: int, lrc: str, txt: str):
    if lrc.strip():
        update_track_synced_lyrics(window.app_state.db, int(track_id), lrc.strip(), (txt or "").strip())
    elif (txt or "").strip():
        update_track_plain_lyrics(window.app_state.db, int(track_id), (txt or "").strip())
    else:
        update_track_null_lyrics(window.app_state.db, int(track_id))
    return get_track_by_id(window.app_state.db, int(track_id))


def mark_track_lyrics_clean(window, track) -> None:
    track_id = int(track.id)
    window.track_list.set_dirty_lyrics_state(track_id, False)
    window.albums_tab.set_dirty_lyrics_state(track_id, False)
    window.artists_tab.set_dirty_lyrics_state(track_id, False)
    window.album_artists_tab.set_dirty_lyrics_state(track_id, False)


def on_dirty_lyrics_changed(window, lrc: str, txt: str) -> None:
    if window._loading_lyrics_views:
        return
    if window._editing_track_id is None:
        return
    window._pending_dirty_lrc = lrc
    window._pending_dirty_txt = txt
    window._dirty_lyrics_timer.start()


def flush_dirty_lyrics(window) -> None:
    track_id = window._editing_track_id
    if track_id is None:
        return
    lrc = window._pending_dirty_lrc
    txt = window._pending_dirty_txt
    try:
        draft_lrc, draft_txt = canonical_lyrics_pair(lrc, txt)
        saved_lrc, saved_txt = window._editing_saved_lyrics
        has_dirty = (draft_lrc, draft_txt) != (saved_lrc, saved_txt)
        if has_dirty:
            update_track_dirty_lyrics(window.app_state.db, int(track_id), draft_lrc, draft_txt)
        else:
            clear_track_dirty_lyrics(window.app_state.db, int(track_id))
        window.track_list.set_dirty_lyrics_state(int(track_id), has_dirty)
        window.albums_tab.set_dirty_lyrics_state(int(track_id), has_dirty)
        window.artists_tab.set_dirty_lyrics_state(int(track_id), has_dirty)
        window.album_artists_tab.set_dirty_lyrics_state(int(track_id), has_dirty)
        for view in window._all_lyrics_views():
            view._set_dirty_badge(has_dirty)
    except sqlite3.Error as exc:
        logger.warning("Failed to save dirty lyrics draft for track %s: %s", track_id, exc)


def on_discard_draft_requested(window) -> None:
    track_id = window._editing_track_id
    if track_id is None:
        return
    try:
        clear_track_dirty_lyrics(window.app_state.db, int(track_id))
        track = get_track_by_id(window.app_state.db, int(track_id))
        window._set_track_lyrics_views(track)
        window._mark_track_lyrics_clean(track)
        window._show_status_message("Draft discarded.", 2500)
    except sqlite3.Error as exc:
        logger.warning("Failed to discard dirty lyrics draft for track %s: %s", track_id, exc)


def download_current_track_lyrics(window) -> None:
    track_id = window._editing_track_id
    if track_id is None:
        notify_user(
            window.app_state,
            "Select a track before downloading lyrics.",
            "warning",
            show_status=window._show_status_message,
            status_timeout_ms=3000,
        )
        return
    window.on_download_lyrics(int(track_id))


def search_current_track_lyrics(window) -> None:
    track_id = window._editing_track_id
    if track_id is None:
        notify_user(
            window.app_state,
            "Select a track before searching lyrics.",
            "warning",
            show_status=window._show_status_message,
            status_timeout_ms=3000,
        )
        return

    track = get_track_by_id(window.app_state.db, int(track_id))
    artist = track.artist_name or ""
    title = track.title or ""
    album = track.album_name or ""

    config = get_config(window.app_state.db)
    lrclib_url = window._normalize_lrclib_base(config.lrclib_instance)

    from ui.dialogs.search_lyrics_dialog import SearchLyricsDialog

    dialog = SearchLyricsDialog(
        lrclib_url,
        db=window.app_state.db,
        initial_artist=artist,
        initial_title=title,
        initial_album=album,
        parent=window,
    )

    def _on_lyrics_selected(plain: str, synced: str):
        synced_text = synced.strip()
        plain_text = plain.strip()
        if synced_text:
            if not plain_text:
                from core.utils import plain_text_from_lrc

                plain_text = plain_text_from_lrc(synced_text)
            update_track_synced_lyrics(window.app_state.db, track_id, synced_text, plain_text)
        elif plain_text:
            update_track_plain_lyrics(window.app_state.db, track_id, plain_text)
        if not synced_text and not plain_text:
            return

        refreshed_track = get_track_by_id(window.app_state.db, track_id)
        window._set_track_lyrics_views(refreshed_track)
        window._show_status_message("Lyrics applied from search.", 3000)
        if not window._sync_track_lyrics_outputs(refreshed_track):
            window._show_status_message("Lyrics output sync is already running.", 3000)

    dialog.lyricsSelected.connect(_on_lyrics_selected)
    dialog.exec()


def export_current_track_sidecars(window) -> None:
    track_id = window._editing_track_id
    if track_id is None:
        notify_user(
            window.app_state,
            "Select or start a track before exporting lyrics files.",
            "warning",
            show_status=window._show_status_message,
            status_timeout_ms=3000,
        )
        for view in window._all_lyrics_views():
            view.set_export_feedback("error", "No Track")
        return
    window._export_track_sidecars(int(track_id))


def export_track_sidecars(window, track_id: int) -> None:
    for view in window._all_lyrics_views():
        view.set_export_feedback("loading", "Exporting...")
    try:
        track = get_track_by_id(window.app_state.db, int(track_id))
        if not (track.lrc_lyrics or track.txt_lyrics):
            notify_user(
                window.app_state,
                "No lyrics are available to export for this track.",
                "warning",
                show_status=window._show_status_message,
                status_timeout_ms=3000,
            )
            for view in window._all_lyrics_views():
                view.set_export_feedback("error", "No Lyrics")
            return

        config = get_config(window.app_state.db)
        export_config = replace(config, save_lyrics_sidecars=True, try_embed_lyrics=False)
        result = sync_track_outputs_with_result(track, export_config)
        written_paths = list(result.sidecar_paths)
        if not written_paths:
            notify_user(
                window.app_state,
                "No lyrics files were generated for this track.",
                "warning",
                show_status=window._show_status_message,
                status_timeout_ms=3000,
            )
            for view in window._all_lyrics_views():
                view.set_export_feedback("error", "Nothing Exported")
            return

        output_dir = os.path.dirname(written_paths[0]) or os.path.dirname(track.file_path)
        notify_user(
            window.app_state,
            "Lyrics files generated successfully.",
            "success",
            show_status=window._show_status_message,
            status_timeout_ms=3000,
        )
        window._show_status_message(f"Lyrics files exported to {output_dir}", 3000)
        for view in window._all_lyrics_views():
            view.set_export_feedback("success", "Exported")
    except (sqlite3.Error, OSError, ValueError) as exc:
        log_and_notify(
            window.app_state,
            logger,
            logging.ERROR,
            exception_message("Failed to export lyrics files", exc),
            "error",
            show_status=window._show_status_message,
            status_timeout_ms=4000,
        )
        for view in window._all_lyrics_views():
            view.set_export_feedback("error", "Export Failed")