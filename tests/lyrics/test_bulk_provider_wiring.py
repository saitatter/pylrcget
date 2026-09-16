from __future__ import annotations

from unittest.mock import Mock

from ui.workers.bulk_lyrics_download_worker import BulkLyricsDownloadWorker


def test_bulk_worker_builds_router_in_configured_provider_priority():
    worker = BulkLyricsDownloadWorker("unused.sqlite", [], "https://lrclib.net/api")
    worker._lyrics_source_settings = {
        "priority": ["tidal", "lrclib"],
        "enabled": {"lrclib": True, "tidal": True, "external": False},
        "tidal": {"country_code": "RO", "transport": "external_helper"},
        "external": {"helper_command": "python helper.py"},
    }
    tidal = Mock()
    tidal.provider_id = "tidal"
    worker._tidal_provider_for_current_thread = Mock(return_value=tidal)

    providers = worker._providers_for_current_thread(Mock(), lambda _message: None)

    assert [provider.provider_id for provider in providers] == ["tidal", "lrclib"]


def test_bulk_worker_skips_tidal_when_transport_is_not_implemented():
    worker = BulkLyricsDownloadWorker("unused.sqlite", [], "https://lrclib.net/api")
    worker._lyrics_source_settings = {
        "priority": ["tidal", "lrclib"],
        "enabled": {"lrclib": True, "tidal": True, "external": False},
        "tidal": {"country_code": "Auto", "transport": "official"},
        "external": {"helper_command": ""},
    }

    providers = worker._providers_for_current_thread(Mock(), lambda _message: None)

    assert [provider.provider_id for provider in providers] == ["lrclib"]
