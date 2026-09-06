from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.lrclib_client import NotFoundError
from ui.services.lyrics_download_service import find_best_lyrics_match


def _fallback_result() -> SimpleNamespace:
    return SimpleNamespace(
        artist_name="Artist",
        track_name="Title",
        album_name="",
        duration=180,
        plain_lyrics="plain lyrics",
        synced_lyrics="[00:01.00]synced lyrics",
        instrumental=False,
    )


def _run_fallback_search(api: Mock) -> object:
    return find_best_lyrics_match(
        api,
        notify=lambda _message: None,
        track_id=1,
        track_label="Artist - Title",
        title="Title",
        artist="Artist",
        album="Album",
        duration_s=180,
    )


def test_early_exit_is_disabled_by_default():
    api = Mock()
    api.get_lyrics.side_effect = NotFoundError(404, "Not Found")
    api.search_lyrics.return_value = [_fallback_result()]

    match = _run_fallback_search(api)

    assert match is not None
    assert match.score == 95
    assert api.search_lyrics.call_count == 5


def test_early_exit_flag_stops_after_high_confidence_match():
    api = Mock()
    api.get_lyrics.side_effect = NotFoundError(404, "Not Found")
    api.search_lyrics.return_value = [_fallback_result()]

    with patch.dict("os.environ", {"PYLRCGET_LRCLIB_EARLY_SCORE": "95"}):
        match = _run_fallback_search(api)

    assert match is not None
    assert match.score == 95
    assert api.search_lyrics.call_count == 1


def test_invalid_early_exit_flag_keeps_current_threshold():
    api = Mock()
    api.get_lyrics.side_effect = NotFoundError(404, "Not Found")
    api.search_lyrics.return_value = [_fallback_result()]

    with patch.dict("os.environ", {"PYLRCGET_LRCLIB_EARLY_SCORE": "90"}):
        _run_fallback_search(api)

    assert api.search_lyrics.call_count == 5
