from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from ui.main_window_parts.lyrics_actions import _on_cleanup_finished


def test_cleanup_completion_refreshes_selected_track_lyrics_from_database():
    track = SimpleNamespace(
        id=42,
        lrc_lyrics=None,
        txt_lyrics=None,
    )
    window = SimpleNamespace(
        _editing_track_id=42,
        _editing_saved_lyrics=("old synced", "old plain"),
        app_state=SimpleNamespace(db=object()),
        _refresh_visible_library_view_after_downloads=Mock(),
        _set_track_lyrics_views=Mock(),
        _update_single_track_lyrics_state=Mock(),
        _show_status_message=Mock(),
        toasts=SimpleNamespace(show_toast=Mock()),
    )

    with (
        patch("ui.main_window_parts.lyrics_actions.get_track_by_id", return_value=track),
        patch("ui.main_window_parts.lyrics_actions.notify_user"),
    ):
        _on_cleanup_finished(
            window,
            True,
            "Lyrics cleared.",
            {"cleaned": 1},
            cleaned_track_ids={42},
        )

    assert window._editing_saved_lyrics == ("", "")
    window._set_track_lyrics_views.assert_called_once_with(track)
    window._update_single_track_lyrics_state.assert_called_once_with(track)


def test_cleanup_completion_does_not_reload_track_that_was_not_cleaned():
    window = SimpleNamespace(
        _editing_track_id=42,
        app_state=SimpleNamespace(db=object()),
        _refresh_visible_library_view_after_downloads=Mock(),
        _set_track_lyrics_views=Mock(),
        _update_single_track_lyrics_state=Mock(),
        _show_status_message=Mock(),
        toasts=SimpleNamespace(show_toast=Mock()),
    )

    with (
        patch("ui.main_window_parts.lyrics_actions.get_track_by_id") as get_track,
        patch("ui.main_window_parts.lyrics_actions.notify_user"),
    ):
        _on_cleanup_finished(
            window,
            False,
            "One track failed.",
            {"cleaned": 1, "failed": 1},
            cleaned_track_ids={7},
        )

    get_track.assert_not_called()
    window._set_track_lyrics_views.assert_not_called()
