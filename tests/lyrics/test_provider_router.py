from __future__ import annotations

import pytest

from lyrics.providers import (
    ACCEPT_FINAL,
    KEEP_AS_FALLBACK,
    LyricsProviderCapabilities,
    LyricsProviderResult,
    LyricsProviderRouter,
    LyricsResultSelector,
    TrackLookupContext,
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
        isrc=None,
    )


def _result(provider: str, *, plain: str | None = None, synced: str | None = None) -> LyricsProviderResult:
    return LyricsProviderResult(
        provider=provider,
        provider_track_id=None,
        plain_lyrics=plain,
        synced_lyrics=synced,
        instrumental=False,
        match_score=100.0,
        match_method="exact metadata",
        remote_title="Song",
        remote_artist="Artist",
        remote_album="Album",
        remote_duration_seconds=180.0,
        remote_isrc=None,
    )


class _FakeProvider:
    provider_id = "fake"
    display_name = "Fake"

    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls = []

    def capabilities(self):
        return LyricsProviderCapabilities(True, True, True, False, False)

    def lookup(self, track, *, requested_mode, cancel_event=None):
        self.calls.append((track, requested_mode, cancel_event))
        if self.error is not None:
            raise self.error
        return self.result


@pytest.mark.parametrize(
    ("mode", "result", "action"),
    [
        ("prefer_synced", _result("fake", synced="[00:01.00]line"), ACCEPT_FINAL),
        ("prefer_synced", _result("fake", plain="plain"), KEEP_AS_FALLBACK),
        ("synced_only", _result("fake", synced="[00:01.00]line"), ACCEPT_FINAL),
        ("synced_only", _result("fake", plain="plain"), KEEP_AS_FALLBACK),
        ("plain_only", _result("fake", synced="[00:01.00]line"), ACCEPT_FINAL),
        ("plain_only", _result("fake", plain="plain"), ACCEPT_FINAL),
    ],
)
def test_selector_keeps_current_download_mode_semantics(mode, result, action):
    decision = LyricsResultSelector().consider(result, mode)

    assert decision.action == action
    assert decision.candidate is result


def test_selector_can_stop_after_plain_result_when_fallback_is_disabled():
    result = _result("fake", plain="plain")

    decision = LyricsResultSelector().consider(
        result,
        "prefer_synced",
        continue_when_plain_for_synced=False,
    )

    assert decision.action == ACCEPT_FINAL
    assert decision.candidate is result


def test_router_prefers_later_synced_result_over_earlier_plain_fallback():
    first = _FakeProvider(_result("first", plain="plain"))
    second = _FakeProvider(_result("second", synced="[00:01.00]synced"))

    result = LyricsProviderRouter((first, second)).lookup(_context(), requested_mode="prefer_synced")

    assert result is not None
    assert result.provider == "second"
    assert first.calls and second.calls


def test_router_returns_first_plain_fallback_when_no_provider_has_synced():
    first = _FakeProvider(_result("first", plain="first plain"))
    second = _FakeProvider(_result("second", plain="second plain"))

    result = LyricsProviderRouter((first, second)).lookup(_context(), requested_mode="prefer_synced")

    assert result is not None
    assert result.provider == "first"
    assert result.plain_lyrics == "first plain"


def test_router_returns_plain_candidate_for_synced_only_mode_after_exhaustion():
    provider = _FakeProvider(_result("fake", plain="plain"))

    result = LyricsProviderRouter((provider,)).lookup(_context(), requested_mode="synced_only")

    assert result is not None
    assert result.plain_lyrics == "plain"
    assert result.synced_lyrics is None


def test_router_continues_after_provider_error_when_another_provider_is_available():
    failing = _FakeProvider(error=RuntimeError("provider unavailable"))
    fallback = _FakeProvider(_result("fallback", plain="plain"))

    result = LyricsProviderRouter((failing, fallback)).lookup(_context(), requested_mode="prefer_synced")

    assert result is not None
    assert result.provider == "fallback"


def test_router_preserves_single_provider_errors_for_lrclib_compatibility():
    provider = _FakeProvider(error=RuntimeError("network unavailable"))

    with pytest.raises(RuntimeError, match="network unavailable"):
        LyricsProviderRouter((provider,)).lookup(_context(), requested_mode="prefer_synced")


def test_router_ignores_empty_instrumental_result():
    provider = _FakeProvider(
        LyricsProviderResult(
            provider="fake",
            provider_track_id=None,
            plain_lyrics=None,
            synced_lyrics=None,
            instrumental=True,
            match_score=100.0,
            match_method="exact metadata",
            remote_title="Song",
            remote_artist="Artist",
            remote_album="Album",
            remote_duration_seconds=180.0,
            remote_isrc=None,
        )
    )

    assert LyricsProviderRouter((provider,)).lookup(_context(), requested_mode="prefer_synced") is None
