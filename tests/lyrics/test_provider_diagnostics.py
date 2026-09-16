from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import Mock

from lyrics.providers import (
    LrclibProvider,
    TrackLookupContext,
    build_lookup_diagnostics,
)


def _context() -> TrackLookupContext:
    return TrackLookupContext(
        track_id=7,
        file_path="C:/Users/secret/Music/song.flac",
        title="Song",
        artists=("Artist",),
        album="Album",
        album_artist="Artist",
        duration_seconds=184.0,
        track_number=1,
        isrc=None,
    )


def test_lookup_diagnostics_has_stable_fields_without_sensitive_defaults():
    diagnostics = build_lookup_diagnostics(
        provider="lrclib",
        track_id=7,
        lookup_method="exact metadata",
        isrc_lookup="not_supported",
        candidate_count=1,
        selected_remote_id="123",
        score=100,
        reason="match",
        result_type="synced",
        elapsed_ms=1.234,
    )

    assert diagnostics == {
        "provider": "lrclib",
        "track_id": 7,
        "lookup_method": "exact metadata",
        "isrc_lookup": "not_supported",
        "candidate_count": 1,
        "selected_remote_id": "123",
        "score": 100.0,
        "reason": "match",
        "result_type": "synced",
        "elapsed_ms": 1.23,
        "cache_hit": False,
        "http_status_category": None,
    }


def test_lrclib_result_and_log_include_provider_diagnostics_without_file_path(caplog):
    api = Mock()
    api.get_lyrics.return_value = SimpleNamespace(
        id=123,
        track_name="Remote Song",
        artist_name="Remote Artist",
        album_name="Remote Album",
        duration=184,
        plain_lyrics="plain",
        synced_lyrics="[00:01.00]synced",
    )
    provider = LrclibProvider("https://lrclib.test/api", api=api)
    caplog.set_level(logging.DEBUG, logger="lyrics.providers.lrclib")

    result = provider.lookup(_context(), requested_mode="prefer_synced")

    assert result is not None
    assert result.diagnostics["provider"] == "lrclib"
    assert result.diagnostics["track_id"] == 7
    assert result.diagnostics["selected_remote_id"] == "123"
    assert result.diagnostics["result_type"] == "synced"
    record = next(item for item in caplog.records if item.name == "lyrics.providers.lrclib")
    assert record.lyrics_lookup["track_id"] == 7
    assert "C:/Users/secret/Music/song.flac" not in record.getMessage()
    assert "secret" not in str(record.lyrics_lookup)
