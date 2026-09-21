from __future__ import annotations

import threading

import pytest

from lyrics.providers import (
    MusixmatchClient,
    MusixmatchError,
    MusixmatchProvider,
    TrackLookupContext,
)
from lyrics.providers.errors import ProviderErrorKind


class _Response:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = payload if isinstance(payload, str) else str(payload)

    def json(self):
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def _context(**overrides) -> TrackLookupContext:
    values = {
        "track_id": 1,
        "file_path": "C:/Music/song.flac",
        "title": "Song",
        "artists": ("Artist",),
        "album": "Album",
        "album_artist": "Artist",
        "duration_seconds": 180.0,
        "track_number": 1,
        "isrc": None,
    }
    values.update(overrides)
    return TrackLookupContext(**values)


def _message(body, status_code=200):
    return {"message": {"header": {"status_code": status_code}, "body": body}}


def _track(track_id="42", title="Song", artist="Artist", album="Album"):
    return {
        "track": {
            "track_id": track_id,
            "track_name": title,
            "artist_name": artist,
            "album_name": album,
            "track_length": 180,
            "track_isrc": "USAAA0000001",
            "has_lyrics": 1,
            "has_subtitles": 1,
            "track_share_url": "https://www.musixmatch.com/lyrics/Artist/Song",
        }
    }


def test_musixmatch_desktop_client_searches_scores_and_reads_lyrics():
    session = _Session(
        [
            _Response(_message({"user_token": "temporary-token"})),
            _Response(
                _message(
                    {
                        "macro_result_list": {
                            "track_list": [
                                _track("bad", "Other Song", "Other Artist"),
                                _track(),
                            ]
                        }
                    }
                )
            ),
            _Response(_message({"subtitle": {"subtitle_body": "[00:01.00]Synced"}})),
            _Response(_message({"lyrics": {"lyrics_body": "Synced"}})),
        ]
    )
    provider = MusixmatchProvider(MusixmatchClient(mode="desktop", session=session))

    result = provider.lookup(_context(), requested_mode="prefer_synced")

    assert result is not None
    assert result.provider == "musixmatch"
    assert result.provider_track_id == "42"
    assert result.synced_lyrics == "[00:01.00]Synced"
    assert result.plain_lyrics == "Synced"
    assert result.match_score == 100.0
    assert result.diagnostics["transport"] == "desktop"
    assert [call[0].rsplit("/", 1)[-1] for call in session.calls] == [
        "token.get",
        "macro.search",
        "track.subtitle.get",
        "track.lyrics.get",
    ]


def test_musixmatch_client_converts_rich_sync_payload_to_lrc():
    from lyrics.providers.musixmatch import _clean_synced_lyrics

    assert _clean_synced_lyrics('[{"ts": 1.25, "x": "Hello"}]') == "[00:01.25]Hello"


def test_musixmatch_website_transport_reads_next_data_lyrics():
    import json

    page = {
        "props": {
            "pageProps": {
                "data": {
                    "trackInfo": {
                        "data": {
                            "track": {
                                "id": 99,
                                "name": "Song",
                                "artistName": "Artist",
                                "albumName": "Album",
                                "duration": 180,
                                "hasLyrics": True,
                                "hasSync": False,
                            },
                            "lyrics": {"body": "Plain lyrics"},
                        }
                    }
                }
            }
        }
    }
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(page)
        + "</script>"
    )
    session = _Session([_Response(html)])
    result = MusixmatchProvider(MusixmatchClient(session=session)).lookup(
        _context(), requested_mode="prefer_synced"
    )

    assert result is not None
    assert result.provider_track_id == "99"
    assert result.plain_lyrics == "Plain lyrics"
    assert result.synced_lyrics is None
    assert session.calls[0][0].endswith("/lyrics/Artist/Song")


def test_musixmatch_official_mode_requires_api_key():
    with pytest.raises(MusixmatchError) as error:
        MusixmatchClient(mode="official")

    assert error.value.kind is ProviderErrorKind.AUTH_REQUIRED


def test_musixmatch_provider_honors_cancellation_before_request():
    session = _Session([])
    provider = MusixmatchProvider(MusixmatchClient(session=session))
    cancelled = threading.Event()
    cancelled.set()

    with pytest.raises(MusixmatchError) as error:
        provider.lookup(_context(), requested_mode="prefer_synced", cancel_event=cancelled)

    assert error.value.kind is ProviderErrorKind.CANCELLED
    assert session.calls == []
