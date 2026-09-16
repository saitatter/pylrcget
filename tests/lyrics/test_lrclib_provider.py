from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from lyrics.providers import LrclibProvider, TrackLookupContext


def test_lrclib_provider_adapts_legacy_match_to_provider_result():
    api = Mock()
    api.get_lyrics.return_value = SimpleNamespace(
        id=123,
        track_name="Remote Song",
        artist_name="Remote Artist",
        album_name="Remote Album",
        duration=184,
        isrc="US-AAA-00-00001",
        instrumental=False,
        plain_lyrics="plain",
        synced_lyrics="[00:01.00]synced",
    )
    provider = LrclibProvider("https://lrclib.test/api", api=api)
    context = TrackLookupContext(
        track_id=7,
        file_path="C:/Music/song.flac",
        title="Song",
        artists=("Artist",),
        album="Album",
        album_artist="Artist",
        duration_seconds=184.0,
        track_number=1,
        isrc=None,
    )

    result = provider.lookup(context, requested_mode="prefer_synced")

    assert result is not None
    assert result.provider == "lrclib"
    assert result.provider_track_id == "123"
    assert result.synced_lyrics == "[00:01.00]synced"
    assert result.remote_artist == "Remote Artist"
    assert result.remote_isrc == "US-AAA-00-00001"
    assert result.match_score == 100.0
