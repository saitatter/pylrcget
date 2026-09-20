from __future__ import annotations

import pytest

from lyrics.providers import (
    LyricsProviderCapabilities,
    LyricsProviderRouter,
    ProviderHealthState,
    TrackLookupContext,
    is_fatal_provider_error,
)
from lyrics.providers.tidal import TidalCatalogueError
from lyrics.providers.tidal_transport import OfficialTidalLyricsError


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


class _FakeProvider:
    provider_id = "tidal"
    display_name = "TIDAL"

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = 0

    def capabilities(self):
        return LyricsProviderCapabilities(True, True, True, False, False)

    def lookup(self, track, *, requested_mode, cancel_event=None):
        del track, requested_mode, cancel_event
        self.calls += 1
        if self.error is not None:
            raise self.error


def test_health_state_disables_fatal_auth_failures_only():
    assert is_fatal_provider_error(TidalCatalogueError(401, "expired")) is True
    assert is_fatal_provider_error(OfficialTidalLyricsError("expired", status_code=401)) is True
    assert is_fatal_provider_error(TidalCatalogueError(429, "slow down")) is False
    assert is_fatal_provider_error(RuntimeError("temporary")) is False


def test_router_skips_provider_after_fatal_batch_failure():
    provider = _FakeProvider(OfficialTidalLyricsError("credentials missing", status_code=401))
    health = ProviderHealthState()
    router = LyricsProviderRouter((provider,))

    with pytest.raises(OfficialTidalLyricsError):
        router.lookup(_context(), requested_mode="prefer_synced", health_state=health)
    assert router.lookup(_context(), requested_mode="prefer_synced", health_state=health) is None
    assert provider.calls == 1


def test_router_does_not_disable_provider_for_transient_error():
    provider = _FakeProvider(RuntimeError("temporary"))
    health = ProviderHealthState()
    router = LyricsProviderRouter((provider,))

    with pytest.raises(RuntimeError):
        router.lookup(_context(), requested_mode="prefer_synced", health_state=health)
    with pytest.raises(RuntimeError):
        router.lookup(_context(), requested_mode="prefer_synced", health_state=health)
    assert provider.calls == 2
