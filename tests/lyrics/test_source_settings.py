from __future__ import annotations

import json

from lyrics.source_settings import (
    load_lyrics_source_settings,
    merge_lyrics_source_settings,
)


def test_source_settings_preserve_lrclib_default_and_disable_musixmatch():
    settings = load_lyrics_source_settings("")

    assert settings["priority"] == ["lrclib", "musixmatch"]
    assert settings["enabled"] == {"lrclib": True, "musixmatch": False}
    assert settings["musixmatch"] == {
        "mode": "website",
        "api_key": "",
    }


def test_source_settings_normalize_priority_and_musixmatch_mode():
    settings = load_lyrics_source_settings(
        json.dumps(
            {
                "lyrics_sources": {
                    "priority": ["MUSIXMATCH", "musixmatch", "lrclib"],
                    "enabled": {"musixmatch": True},
                    "musixmatch": {"mode": "invalid", "api_key": " key "},
                }
            }
        )
    )

    assert settings["priority"] == ["musixmatch", "lrclib"]
    assert settings["enabled"]["musixmatch"] is True
    assert settings["musixmatch"] == {"mode": "website", "api_key": "key"}


def test_source_settings_ignore_removed_tidal_configuration():
    settings = load_lyrics_source_settings(
        json.dumps(
            {
                "lyrics_sources": {
                    "tidal": {"client_id": "custom-client"},
                }
            }
        )
    )

    assert "tidal" not in settings
    assert settings["enabled"]["musixmatch"] is False


def test_source_settings_merge_preserves_unrelated_ui_state():
    merged = merge_lyrics_source_settings(
        json.dumps({"editor_auto_edit_on_add_line": True}),
        {"priority": ["musixmatch"], "enabled": {"musixmatch": True}},
    )

    state = json.loads(merged)
    assert state["editor_auto_edit_on_add_line"] is True
    assert state["lyrics_sources"]["enabled"]["musixmatch"] is True


def test_source_settings_drop_removed_external_helper_configuration():
    settings = load_lyrics_source_settings(
        json.dumps(
            {
                "lyrics_sources": {
                    "priority": ["external", "lrclib"],
                    "enabled": {"external": True, "lrclib": True},
                    "external": {"helper_command": "python tidal_helper.py"},
                    "tidal": {"transport": "external_helper", "helper_command": "python tidal_helper.py"},
                }
            }
        )
    )

    assert settings["priority"] == ["lrclib", "musixmatch"]
    assert settings["enabled"] == {"lrclib": True, "musixmatch": False}
    assert settings["musixmatch"]["mode"] == "website"
    assert "helper_command" not in settings["musixmatch"]
    assert "external" not in settings
