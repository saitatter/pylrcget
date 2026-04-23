from __future__ import annotations

import logging
import sqlite3
from typing import Callable

from PySide6.QtCore import QObject

from db.queries import get_config, get_track_by_id, record_publish_history
from ui.dialogs.publish_lyrics_dialog import PublishLyricsDialog, lint_lyrics
from ui.services.feedback import notify_user

logger = logging.getLogger(__name__)


class PublishHistoryController(QObject):
    def __init__(
        self,
        app_state,
        *,
        normalize_lrclib_base: Callable[[str], str],
        current_player_track_id: Callable[[], int | None],
        lyrics_views: Callable[[], list],
        refresh_history: Callable[[], None],
        show_status: Callable[[str, int | None], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._normalize_lrclib_base = normalize_lrclib_base
        self._current_player_track_id = current_player_track_id
        self._lyrics_views = lyrics_views
        self._refresh_history = refresh_history
        self._show_status = show_status

    def publish_synced(self) -> None:
        self._open_publish_dialog(is_synced=True)

    def publish_plain(self) -> None:
        self._open_publish_dialog(is_synced=False)

    def _open_publish_dialog(self, *, is_synced: bool) -> None:
        track_id = self._current_player_track_id()
        if track_id is None:
            notify_user(
                self._app_state,
                "Start playback or select a track first.",
                "warning",
                show_status=self._show_status,
                status_timeout_ms=3000,
            )
            for view in self._lyrics_views():
                view.set_publish_feedback(is_synced=is_synced, state="error", message="No Track")
            return

        track = get_track_by_id(self._app_state.db, int(track_id))
        lyrics_text = (track.lrc_lyrics or "") if is_synced else (track.txt_lyrics or "")
        lint_result = lint_lyrics(lyrics_text, is_synced=is_synced)
        dlg = PublishLyricsDialog(
            title=track.title,
            artist_name=track.artist_name,
            album_name=track.album_name,
            duration_s=float(track.duration or 0.0),
            lyrics_text=lyrics_text,
            is_synced=is_synced,
            lint_result=[p for p in lint_result if p.severity == "error"],
            lrclib_instance=self._normalize_lrclib_base(get_config(self._app_state.db).lrclib_instance),
            parent=self.parent(),
        )
        for view in self._lyrics_views():
            view.set_publish_feedback(is_synced=is_synced, state="loading", message="Publishing...")
        dlg.exec()

        if dlg.publish_result is True:
            try:
                record_publish_history(
                    self._app_state.db,
                    track_id=int(track.id),
                    title=track.title,
                    artist_name=track.artist_name,
                    album_name=track.album_name,
                    publish_kind="synced" if is_synced else "plain",
                    lrclib_instance=self._normalize_lrclib_base(get_config(self._app_state.db).lrclib_instance),
                )
            except (sqlite3.Error, AttributeError) as exc:
                logger.warning("Failed to record publish history: %s", exc)
            else:
                self._refresh_history()
            for view in self._lyrics_views():
                view.set_publish_feedback(is_synced=is_synced, state="success", message="Published")
            notify_user(
                self._app_state,
                "Lyrics published successfully.",
                "success",
                show_status=self._show_status,
                status_timeout_ms=3000,
            )
            return

        if dlg.publish_result is False:
            for view in self._lyrics_views():
                view.set_publish_feedback(is_synced=is_synced, state="error", message="Publish Failed")
            return

        for view in self._lyrics_views():
            view.set_publish_feedback(is_synced=is_synced, state="idle")
