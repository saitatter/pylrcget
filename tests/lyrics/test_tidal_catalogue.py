from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lyrics.providers import (
    MatchQuality,
    TidalCatalogueClient,
    TidalCatalogueError,
    TrackLookupContext,
)


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
        "isrc": "USAAA0000001",
    }
    values.update(overrides)
    return TrackLookupContext(**values)


def _response(payload, status_code=200):
    return SimpleNamespace(
        status_code=status_code,
        text="error" if status_code >= 400 else "",
        json=lambda: payload,
    )


def _catalogue_payload():
    return {
        "data": [
            {
                "type": "tracks",
                "id": "123",
                "attributes": {
                    "title": "Song",
                    "duration": 180,
                    "trackNumber": 1,
                    "isrc": "US-AAA-00-00001",
                },
                "relationships": {
                    "artists": {"data": [{"type": "artists", "id": "artist-1"}]},
                    "albums": {"data": [{"type": "albums", "id": "album-1"}]},
                },
            }
        ],
        "included": [
            {"type": "artists", "id": "artist-1", "attributes": {"name": "Artist"}},
            {"type": "albums", "id": "album-1", "attributes": {"title": "Album"}},
        ],
    }


def test_lookup_by_isrc_parses_nested_artist_and_album_relationships():
    session = Mock()
    session.get.return_value = _response(_catalogue_payload())
    client = TidalCatalogueClient(
        "token",
        country_code="Auto",
        base_url="https://openapi.tidal.test/v2",
        session=session,
    )

    tracks = client.lookup_by_isrc("us-aaa-00-00001")

    assert tracks[0].provider_track_id == "123"
    assert tracks[0].artists == ("Artist",)
    assert tracks[0].album == "Album"
    assert tracks[0].isrc == "USAAA0000001"
    request = session.get.call_args
    assert request.args[0] == "https://openapi.tidal.test/v2/tracks"
    assert request.kwargs["params"]["filter[isrc]"] == "USAAA0000001"
    assert "countryCode" not in request.kwargs["params"]
    assert request.kwargs["headers"]["Authorization"] == "Bearer token"


def test_explicit_country_code_is_sent_without_defaulting_everyone_to_us():
    session = Mock()
    session.get.return_value = _response({"data": []})
    client = TidalCatalogueClient("token", country_code="ro", session=session)

    client.lookup_by_isrc("USAAA0000001")

    assert session.get.call_args.kwargs["params"]["countryCode"] == "RO"


def test_resolver_prefers_exact_isrc_and_does_not_search_again():
    session = Mock()
    session.get.return_value = _response(_catalogue_payload())
    client = TidalCatalogueClient("token", session=session)

    resolution = client.resolve_track(_context())

    assert resolution is not None
    assert resolution.track.provider_track_id == "123"
    assert resolution.score.quality is MatchQuality.EXACT_ID
    assert session.get.call_count == 1


def test_resolver_falls_back_to_metadata_search_when_isrc_has_no_result():
    session = Mock()
    session.get.side_effect = [
        _response({"data": []}),
        _response(
            {
                "data": [
                    {
                        "id": "456",
                        "attributes": {"title": "Song", "duration": 181},
                        "relationships": {"artists": {"data": []}},
                    }
                ]
            }
        ),
    ]
    client = TidalCatalogueClient("token", session=session)

    resolution = client.resolve_track(_context(isrc=None, album=None))

    assert resolution is None
    assert session.get.call_count == 1


def test_search_is_used_when_local_track_has_no_isrc():
    session = Mock()
    session.get.return_value = _response(
        {
            "data": [
                {
                    "id": "456",
                    "attributes": {"title": "Song", "artist": "Artist", "duration": 180},
                    "relationships": {
                        "artists": {"data": []},
                    },
                }
            ]
        }
    )
    client = TidalCatalogueClient("token", session=session)

    resolution = client.resolve_track(_context(isrc=None, album=None))

    assert resolution is not None
    assert resolution.track.provider_track_id == "456"
    assert session.get.call_count == 1
    assert "/searchResults/Artist%20Song/relationships/tracks" in session.get.call_args.args[0]


def test_http_errors_are_explicit_and_invalid_json_is_not_accepted():
    session = Mock()
    session.get.return_value = _response({}, status_code=500)
    client = TidalCatalogueClient("token", session=session)

    with pytest.raises(TidalCatalogueError, match="500"):
        client.lookup_by_isrc("USAAA0000001")

    session.get.return_value = SimpleNamespace(status_code=200, text="not-json", json=lambda: (_ for _ in ()).throw(ValueError()))
    with pytest.raises(TidalCatalogueError, match="Invalid JSON"):
        client.lookup_by_isrc("USAAA0000001")
