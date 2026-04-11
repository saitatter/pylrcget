from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject

from db.database import get_config, get_track_by_id
from db.queries import record_publish_history
from ui.dialogs.publish_lyrics_dialog import PublishLyricsDialog

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
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._normalize_lrclib_base = normalize_lrclib_base
        self._current_player_track_id = current_player_track_id
        self._lyrics_views = lyrics_views
        self._refresh_history = refresh_history

    def publish_synced(self) -> None:
        self._open_publish_dialog(is_synced=True)

    def publish_plain(self) -> None:
        self._open_publish_dialog(is_synced=False)

    def _open_publish_dialog(self, *, is_synced: bool) -> None:
        track_id = self._current_player_track_id()
        if track_id is None:
            self._app_state.notify("Start playback or select a track first.", "warning")
            for view in self._lyrics_views():
                view.set_publish_feedback(is_synced=is_synced, state="error", message="No Track")
            return

        track = get_track_by_id(self._app_state.db, int(track_id))
        lyrics_text = (track.lrc_lyrics or "") if is_synced else (track.txt_lyrics or "")
        dlg = PublishLyricsDialog(
            title=track.title,
            artist_name=track.artist_name,
            album_name=track.album_name,
            duration_s=float(track.duration or 0.0),
            lyrics_text=lyrics_text,
            is_synced=is_synced,
            lint_result=[],
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
            except Exception as exc:
                logger.warning("Failed to record publish history: %s", exc)
            else:
                self._refresh_history()
            for view in self._lyrics_views():
                view.set_publish_feedback(is_synced=is_synced, state="success", message="Published")
            self._app_state.notify("Lyrics published successfully.", "success")
            return

        if dlg.publish_result is False:
            for view in self._lyrics_views():
                view.set_publish_feedback(is_synced=is_synced, state="error", message="Publish Failed")
            return

        for view in self._lyrics_views():
            view.set_publish_feedback(is_synced=is_synced, state="idle")
