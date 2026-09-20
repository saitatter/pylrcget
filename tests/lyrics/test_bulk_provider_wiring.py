from __future__ import annotations

from unittest.mock import Mock

from lyrics.providers import TidalAccessContext
from ui.workers.bulk_lyrics_download_worker import BulkLyricsDownloadWorker


def test_bulk_worker_builds_router_in_configured_provider_priority():
    worker = BulkLyricsDownloadWorker("unused.sqlite", [], "https://lrclib.net/api")
    worker._lyrics_source_settings = {
        "priority": ["tidal", "lrclib"],
        "enabled": {"lrclib": True, "tidal": True},
        "tidal": {
            "country_code": "RO",
            "transport": "external_helper",
            "helper_command": "python helper.py",
        },
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
        "enabled": {"lrclib": True, "tidal": True},
        "tidal": {"country_code": "Auto", "transport": "official"},
    }

    providers = worker._providers_for_current_thread(Mock(), lambda _message: None)

    assert [provider.provider_id for provider in providers] == ["lrclib"]


def test_bulk_worker_never_constructs_disabled_lrclib_provider():
    worker = BulkLyricsDownloadWorker("unused.sqlite", [], "https://lrclib.net/api")
    worker._lyrics_source_settings = {
        "priority": ["lrclib", "tidal"],
        "enabled": {"lrclib": False, "tidal": True},
        "tidal": {
            "country_code": "RO",
            "transport": "external_helper",
            "helper_command": "python helper.py",
        },
    }
    tidal = Mock()
    tidal.provider_id = "tidal"
    worker._tidal_provider_for_current_thread = Mock(return_value=tidal)

    providers = worker._providers_for_current_thread(Mock(), lambda _message: None)

    assert [provider.provider_id for provider in providers] == ["tidal"]


def test_bulk_worker_builds_native_tidal_provider_without_helper(tmp_path, monkeypatch):
    worker = BulkLyricsDownloadWorker(str(tmp_path / "tidal.sqlite"), [], "https://lrclib.net/api")
    worker._lyrics_source_settings = {
        "priority": ["tidal", "lrclib"],
        "enabled": {"lrclib": True, "tidal": True},
        "tidal": {
            "country_code": "RO",
            "transport": "official",
            "client_id": "client-id",
            "redirect_uri": "http://127.0.0.1:8765/callback",
        },
    }
    auth = Mock()
    auth.return_value.get_access_context.return_value = TidalAccessContext("access-token")
    transport = Mock()
    transport_factory = Mock(return_value=transport)
    monkeypatch.setattr("ui.workers.bulk_lyrics_download_worker.TidalOAuthSession", auth)
    monkeypatch.setattr(
        "ui.workers.bulk_lyrics_download_worker.OfficialTidalLyricsTransport",
        transport_factory,
    )

    provider = worker._tidal_provider_for_current_thread()

    assert provider is not None
    assert provider.provider_id == "tidal"
    auth.assert_called_once_with("client-id", "http://127.0.0.1:8765/callback")
    transport_factory.assert_called_once()
    assert worker._thread_local.tidal_mapping_db is not None
    worker._thread_local.tidal_mapping_db.close()
