from __future__ import annotations

from unittest.mock import Mock

from lyrics.providers import MusixmatchClient
from ui.workers.bulk_lyrics_download_worker import BulkLyricsDownloadWorker


def test_bulk_worker_builds_router_in_configured_provider_priority():
    worker = BulkLyricsDownloadWorker("unused.sqlite", [], "https://lrclib.net/api")
    worker._lyrics_source_settings = {
        "priority": ["musixmatch", "lrclib"],
        "enabled": {"lrclib": True, "musixmatch": True},
        "musixmatch": {"mode": "desktop"},
    }
    musixmatch = Mock()
    musixmatch.provider_id = "musixmatch"
    worker._musixmatch_provider_for_current_thread = Mock(return_value=musixmatch)

    providers = worker._providers_for_current_thread(Mock(), lambda _message: None)

    assert [provider.provider_id for provider in providers] == ["musixmatch", "lrclib"]


def test_bulk_worker_skips_musixmatch_when_configuration_is_invalid():
    worker = BulkLyricsDownloadWorker("unused.sqlite", [], "https://lrclib.net/api")
    worker._lyrics_source_settings = {
        "priority": ["musixmatch", "lrclib"],
        "enabled": {"lrclib": True, "musixmatch": True},
        "musixmatch": {"mode": "official", "api_key": ""},
    }

    providers = worker._providers_for_current_thread(Mock(), lambda _message: None)

    assert [provider.provider_id for provider in providers] == ["lrclib"]


def test_bulk_worker_never_constructs_disabled_lrclib_provider():
    worker = BulkLyricsDownloadWorker("unused.sqlite", [], "https://lrclib.net/api")
    worker._lyrics_source_settings = {
        "priority": ["lrclib", "musixmatch"],
        "enabled": {"lrclib": False, "musixmatch": True},
        "musixmatch": {"mode": "desktop"},
    }
    musixmatch = Mock()
    musixmatch.provider_id = "musixmatch"
    worker._musixmatch_provider_for_current_thread = Mock(return_value=musixmatch)

    providers = worker._providers_for_current_thread(Mock(), lambda _message: None)

    assert [provider.provider_id for provider in providers] == ["musixmatch"]


def test_bulk_worker_builds_native_musixmatch_provider_without_helper(tmp_path, monkeypatch):
    worker = BulkLyricsDownloadWorker(str(tmp_path / "musixmatch.sqlite"), [], "https://lrclib.net/api")
    worker._lyrics_source_settings = {
        "priority": ["musixmatch", "lrclib"],
        "enabled": {"lrclib": True, "musixmatch": True},
        "musixmatch": {"mode": "official", "api_key": "api-key"},
    }
    monkeypatch.setattr("ui.workers.bulk_lyrics_download_worker.MusixmatchClient", Mock(wraps=MusixmatchClient))

    provider = worker._musixmatch_provider_for_current_thread()

    assert provider is not None
    assert provider.provider_id == "musixmatch"
