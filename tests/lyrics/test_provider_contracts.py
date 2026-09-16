from __future__ import annotations

import threading

from lyrics.providers import (
    LyricsProviderCapabilities,
    LyricsProviderResult,
    TrackLookupContext,
)


def test_track_lookup_context_is_provider_neutral_and_immutable():
    context = TrackLookupContext(
        track_id=7,
        file_path="C:/Music/song.flac",
        title="Song",
        artists=("Artist",),
        album="Album",
        album_artist="Artist",
        duration_seconds=183.5,
        track_number=2,
        isrc="US-AAA-00-00001",
    )

    assert context.artists == ("Artist",)
    assert context.duration_seconds == 183.5
    assert context.isrc == "US-AAA-00-00001"


def test_provider_result_keeps_lyrics_provenance_and_isolates_diagnostics():
    first = LyricsProviderResult(
        provider="lrclib",
        provider_track_id="123",
        plain_lyrics="plain",
        synced_lyrics="[00:01.00]synced",
        instrumental=False,
        match_score=100.0,
        match_method="exact metadata",
        remote_title="Song",
        remote_artist="Artist",
        remote_album="Album",
        remote_duration_seconds=183.0,
        remote_isrc="US-AAA-00-00001",
    )
    second = LyricsProviderResult(
        provider="tidal",
        provider_track_id=None,
        plain_lyrics=None,
        synced_lyrics=None,
        instrumental=False,
        match_score=0.0,
        match_method="not found",
        remote_title=None,
        remote_artist=None,
        remote_album=None,
        remote_duration_seconds=None,
        remote_isrc=None,
    )

    first.diagnostics["query_count"] = 1

    assert first.provider == "lrclib"
    assert first.synced_lyrics == "[00:01.00]synced"
    assert first.diagnostics == {"query_count": 1}
    assert second.diagnostics == {}


def test_provider_capabilities_are_value_objects():
    capabilities = LyricsProviderCapabilities(
        plain=True,
        synced=True,
        search=True,
        isrc_lookup=False,
        authentication_required=False,
    )

    assert capabilities.synced is True
    assert capabilities.isrc_lookup is False


def test_provider_lookup_boundary_uses_context_and_cancellation_event():
    context = TrackLookupContext(
        track_id=None,
        file_path="C:/Music/song.flac",
        title="Song",
        artists=("Artist",),
        album=None,
        album_artist=None,
        duration_seconds=None,
        track_number=None,
        isrc=None,
    )
    cancel_event = threading.Event()
    calls: list[tuple[TrackLookupContext, str, threading.Event | None]] = []

    class FakeProvider:
        provider_id = "fake"
        display_name = "Fake"

        def capabilities(self):
            return LyricsProviderCapabilities(True, False, True, False, False)

        def lookup(self, track, *, requested_mode, cancel_event=None):
            calls.append((track, requested_mode, cancel_event))

    provider = FakeProvider()
    provider.lookup(context, requested_mode="prefer_synced", cancel_event=cancel_event)

    assert calls == [(context, "prefer_synced", cancel_event)]
