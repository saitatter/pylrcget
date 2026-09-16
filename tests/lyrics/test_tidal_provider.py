from __future__ import annotations

import threading

from lyrics.providers import (
    MatchQuality,
    TidalLyricsPayload,
    TidalProvider,
    TidalTrack,
    TidalTrackResolution,
    TrackLookupContext,
    TrackMatchScore,
)


def _context() -> TrackLookupContext:
    return TrackLookupContext(
        track_id=1,
        file_path="C:/Music/song.flac",
        title="Song",
        artists=("Artist",),
        album="Album",
        album_artist="Artist",
        duration_seconds=180.0,
        track_number=1,
        isrc="USAAA0000001",
    )


def _resolution() -> TidalTrackResolution:
    return TidalTrackResolution(
        track=TidalTrack(
            provider_track_id="123",
            title="Song",
            artists=("Artist",),
            album="Album",
            album_artist="Artist",
            duration_seconds=180.0,
            track_number=1,
            isrc="USAAA0000001",
        ),
        score=TrackMatchScore(100.0, MatchQuality.EXACT_ID, "exact isrc"),
    )


class _Resolver:
    def __init__(self, resolution):
        self.resolution = resolution
        self.calls = []

    def resolve_track(self, track):
        self.calls.append(track)
        return self.resolution


class _Transport:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_lyrics(self, tidal_track_id, *, cancel_event=None, track=None, requested_mode="prefer_synced"):
        self.calls.append((tidal_track_id, cancel_event, track, requested_mode))
        return self.payload


def test_tidal_provider_resolves_catalogue_then_fetches_transport_payload():
    resolver = _Resolver(_resolution())
    transport = _Transport(TidalLyricsPayload("plain", "[00:01.00]synced", "external"))

    result = TidalProvider(resolver, transport).lookup(_context(), requested_mode="prefer_synced")

    assert result is not None
    assert result.provider == "tidal"
    assert result.provider_track_id == "123"
    assert result.remote_artist == "Artist"
    assert result.synced_lyrics == "[00:01.00]synced"
    assert result.diagnostics["transport_source"] == "external"
    assert result.diagnostics["selected_remote_id"] == "123"
    assert resolver.calls and transport.calls[0][0] == "123"
    assert transport.calls[0][2] == _context()


def test_tidal_provider_returns_clean_miss_without_transport_call():
    resolver = _Resolver(None)
    transport = _Transport(TidalLyricsPayload("plain", None))

    assert TidalProvider(resolver, transport).lookup(_context(), requested_mode="prefer_synced") is None
    assert transport.calls == []


def test_tidal_provider_honors_cancellation_before_catalogue_request():
    resolver = _Resolver(_resolution())
    transport = _Transport(TidalLyricsPayload("plain", None))
    cancelled = threading.Event()
    cancelled.set()

    assert (
        TidalProvider(resolver, transport).lookup(
            _context(),
            requested_mode="prefer_synced",
            cancel_event=cancelled,
        )
        is None
    )
    assert resolver.calls == []
