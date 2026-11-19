from __future__ import annotations

from dataclasses import replace
from unittest.mock import Mock

import pytest
import requests

from core.lrclib_client import LrcLibAPI, NotFoundError, RateLimitError, ServerError
from tests import test_support as _test_support  # noqa: F401
from ui.services.lyrics_download_service import (
    LyricsMatchCancelled,
    find_best_lyrics_match,
)


def _summary(**overrides):
    return {
        "id": 7, "trackName": "Song", "artistName": "Artist", "albumName": "Album",
        "duration": 180, "hasPlainLyrics": True, "hasSyncedLyrics": True,
        "hasWordSync": True, **overrides,
    }


def _api(*responses):
    api = LrcLibAPI("https://example.test/api")
    api._request = Mock(side_effect=responses)
    return api


def _response(payload):
    return Mock(json=Mock(return_value=payload))


def test_v2_search_keeps_flags_without_downloading_lyrics():
    api = _api(_response([_summary()]))
    result, = api.search_lyrics(query=" Song ", artist_name="ignored")
    assert result.track_name == result.name == "Song"
    assert result.has_plain_lyrics and result.has_synced_lyrics and result.has_word_sync
    assert result.plain_lyrics is result.synced_lyrics is None
    assert result.lyrics_loaded is False
    api._request.assert_called_once_with("GET", "/v2/search", params={"q": "Song"})


@pytest.mark.parametrize("unsupported", [
    NotFoundError(404, "Not Found"),
    Mock(json=Mock(side_effect=ValueError("HTML application"))),
])
def test_old_instance_falls_back_and_remembers_missing_v2_route(unsupported):
    legacy = _response([_summary(plainLyrics="plain", syncedLyrics="[00:01.00]line")])
    api = _api(unsupported, legacy, legacy)
    first, = api.search_lyrics(track_name="Song", artist_name="Artist", album_name="")
    second, = api.search_lyrics(track_name="Song")
    assert first.lyrics_loaded and second.lyrics_loaded
    assert first.plain_lyrics == "plain"
    assert [call.args[1] for call in api._request.call_args_list] == ["/v2/search", "/search", "/search"]
    assert api._request.call_args_list[0].kwargs["params"] == {"track_name": "Song", "artist_name": "Artist"}


@pytest.mark.parametrize("error", [
    RateLimitError(429, "Too Many Requests"), ServerError(503, "Unavailable"),
    requests.Timeout("timeout"), requests.ConnectionError("offline"), InterruptedError("cancelled"),
])
def test_operational_failures_never_trigger_v1_fallback(error):
    api = _api(error)
    with pytest.raises(type(error)):
        api.search_lyrics(query="Song")
    assert api._request.call_count == 1
    assert api._search_v2_supported is True


def test_empty_v2_results_do_not_trigger_v1_fallback():
    api = _api(_response([]))
    assert api.search_lyrics(query="Song") == []
    assert api._request.call_count == 1


def test_invalid_json_shape_surfaces_without_falling_back():
    api = _api(_response({"error": "unexpected"}))
    with pytest.raises(ValueError, match="Invalid LRCLIB v2"):
        api.search_lyrics(query="Song")
    assert api._request.call_count == 1


def _find(api, **kwargs):
    return find_best_lyrics_match(
        api, notify=lambda _: None, track_id=1, track_label="Artist - Song", title="Song",
        artist="Artist", album="Album", duration_s=180, **kwargs,
    )


def _fallback_api():
    api = _api(_response([_summary(id=8, trackName="Unrelated"), _summary()]))
    results = api.search_lyrics(query="Song")
    api.get_lyrics = Mock(side_effect=NotFoundError(404, "Not Found"))
    api.search_lyrics = Mock(return_value=results)
    api.get_lyrics_by_id = Mock(return_value=Mock(plain_lyrics="plain", synced_lyrics="[00:01.00]line"))
    return api


def test_fallback_download_fetches_only_the_best_summary():
    api = _fallback_api()
    match = _find(api)
    assert match.result.id == 7
    assert match.result.synced_lyrics == "[00:01.00]line"
    api.get_lyrics_by_id.assert_called_once_with(7)


def test_cancel_before_selected_record_fetch_does_not_download_lyrics():
    api = _fallback_api()
    def before_request():
        return api.search_lyrics.call_count == 0
    with pytest.raises(LyricsMatchCancelled):
        _find(api, before_request=before_request)
    api.get_lyrics_by_id.assert_not_called()


def test_removed_lyrics_are_not_returned_as_an_empty_match():
    api = _fallback_api()
    api.get_lyrics_by_id.return_value = Mock(plain_lyrics=None, synced_lyrics=None)
    assert _find(api) is None


def test_synced_only_search_continues_after_an_exact_plain_match_and_stale_summary():
    api = _api(_response([
        _summary(id=6, hasSyncedLyrics=False),
        _summary(),
        _summary(id=8, trackName="Song (Live)"),
        _summary(id=9, artistName="Another Artist"),
    ]))
    api.search_lyrics = Mock(return_value=api.search_lyrics(query="Song"))
    api.get_lyrics = Mock(return_value=Mock(plain_lyrics="exact plain", synced_lyrics=None))
    api.get_lyrics_by_id = Mock(side_effect=[
        Mock(plain_lyrics="stale plain", synced_lyrics=None),
        Mock(plain_lyrics=None, synced_lyrics="[00:01.00]live line"),
    ])

    match = _find(api, synced_only=True)

    assert match.result.id == 8
    assert match.result.synced_lyrics == "[00:01.00]live line"
    assert match.score < 100
    assert [call.args[0] for call in api.get_lyrics_by_id.call_args_list] == [7, 8]


def test_synced_only_search_tries_the_movement_title_with_artist_and_album():
    api = _fallback_api()
    result = replace(
        api.search_lyrics.return_value[-1], track_name="2112: Grand Finale", artist_name="Rush",
        album_name="Different Stages",
    )
    api.search_lyrics.side_effect = lambda **params: [result] if params["track_name"] == "Grand Finale" else []
    api.get_lyrics.return_value = Mock(plain_lyrics="exact plain", synced_lyrics=None)
    api.get_lyrics.side_effect = None

    match = find_best_lyrics_match(
        api, notify=lambda _: None, track_id=1, track_label="Rush - 2112 - VII. Grand Finale",
        title="2112 - VII. Grand Finale", artist="Rush", album="Different Stages", duration_s=180, synced_only=True,
    )

    assert match.query_label == "movement title"
    assert match.score < 100
    api.search_lyrics.assert_called_with(query=None, track_name="Grand Finale", artist_name="Rush", album_name="Different Stages")


def test_retry_search_fetches_only_the_selected_record():
    from ui.workers.lyrics_retry_search_worker import (
        LyricsRetrySearchWorker,
        _RetryTrack,
    )
    api = _fallback_api()
    worker = LyricsRetrySearchWorker("unused.sqlite", [], "https://example.test/api")
    worker._api_for_current_thread = lambda: api
    candidate = worker._search_retry_track(_RetryTrack(1, "Artist - Song", "Artist", "Song", "Album"))
    assert candidate.lyrics_loaded
    assert candidate.synced_lyrics == "[00:01.00]line"
    api.get_lyrics_by_id.assert_called_once_with(7)


def test_synced_only_retry_search_filters_plain_results():
    from ui.workers.lyrics_retry_search_worker import (
        LyricsRetrySearchWorker,
        _RetryTrack,
    )

    api = _api(_response([_summary(hasSyncedLyrics=False)]))
    api.search_lyrics = Mock(return_value=api.search_lyrics(query="Song"))
    worker = LyricsRetrySearchWorker(
        "unused.sqlite", [], "https://example.test/api", download_mode="synced_only",
    )
    worker._api_for_current_thread = lambda: api

    assert worker._search_retry_track(_RetryTrack(1, "Artist - Song", "Artist", "Song", "Album")) is None
    api._request.assert_called_once()


def test_legacy_results_do_not_request_their_lyrics_again():
    api = _fallback_api()
    api.search_lyrics.return_value = [replace(
        api.search_lyrics.return_value[-1], lyrics_loaded=True, plain_lyrics="legacy",
    )]
    assert _find(api).result.plain_lyrics == "legacy"
    api.get_lyrics_by_id.assert_not_called()
