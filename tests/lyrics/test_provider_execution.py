from __future__ import annotations

import pytest

from lyrics.providers import (
    LyricsProviderCapabilities,
    LyricsProviderRouter,
    ProviderExecutionCoordinator,
    ProviderExecutionPolicy,
    TrackLookupContext,
    get_provider_execution_policy,
)


def test_provider_policies_are_conservative_and_lrclib_keeps_current_limit():
    assert get_provider_execution_policy("lrclib").max_concurrency == 4
    assert get_provider_execution_policy("tidal").max_concurrency == 2
    assert get_provider_execution_policy("external").max_concurrency == 1


def test_unknown_provider_defaults_to_single_worker():
    assert get_provider_execution_policy("future-provider").max_concurrency == 1


def test_provider_execution_policy_rejects_invalid_limits():
    with pytest.raises(ValueError):
        ProviderExecutionPolicy(max_concurrency=0)
    with pytest.raises(ValueError):
        ProviderExecutionPolicy(max_concurrency=1, min_request_interval=-1)


def test_execution_coordinator_allows_and_releases_provider_slot():
    coordinator = ProviderExecutionCoordinator()

    assert coordinator.acquire("lrclib", lambda: False) is True
    coordinator.release("lrclib")


def test_execution_coordinator_records_provider_specific_rate_limit():
    coordinator = ProviderExecutionCoordinator()

    coordinator.record_rate_limit("tidal", 0.0)
    assert coordinator.acquire("lrclib", lambda: False) is True
    coordinator.release("lrclib")


def test_router_releases_provider_slot_after_lookup():
    class Provider:
        provider_id = "lrclib"
        display_name = "LRCLIB"

        def capabilities(self):
            return LyricsProviderCapabilities(True, True, True, False, False)

        def lookup(self, track, *, requested_mode, cancel_event=None):
            del track, requested_mode, cancel_event

    track = TrackLookupContext(1, "song.mp3", "Song", ("Artist",), "Album", "Artist", 180.0, 1, None)
    coordinator = ProviderExecutionCoordinator()

    assert LyricsProviderRouter((Provider(),)).lookup(
        track,
        requested_mode="prefer_synced",
        execution_coordinator=coordinator,
    ) is None
    assert coordinator.acquire("lrclib", lambda: False) is True
    coordinator.release("lrclib")
