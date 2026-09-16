from __future__ import annotations

import json

from lyrics.source_settings import (
    load_lyrics_source_settings,
    merge_lyrics_source_settings,
)


def test_source_settings_preserve_lrclib_default_and_disable_new_providers():
    settings = load_lyrics_source_settings("")

    assert settings["priority"] == ["lrclib", "tidal", "external"]
    assert settings["enabled"] == {"lrclib": True, "tidal": False, "external": False}
    assert settings["tidal"] == {"country_code": "Auto", "transport": "external_helper"}


def test_source_settings_normalize_priority_country_and_transport():
    settings = load_lyrics_source_settings(
        json.dumps(
            {
                "lyrics_sources": {
                    "priority": ["TIDAL", "tidal", "lrclib"],
                    "enabled": {"tidal": True},
                    "tidal": {"country_code": "ro", "transport": "invalid"},
                }
            }
        )
    )

    assert settings["priority"] == ["tidal", "lrclib", "external"]
    assert settings["enabled"]["tidal"] is True
    assert settings["tidal"] == {"country_code": "RO", "transport": "external_helper"}


def test_source_settings_merge_preserves_unrelated_ui_state():
    merged = merge_lyrics_source_settings(
        json.dumps({"editor_auto_edit_on_add_line": True}),
        {"priority": ["external"], "enabled": {"external": True}},
    )

    state = json.loads(merged)
    assert state["editor_auto_edit_on_add_line"] is True
    assert state["lyrics_sources"]["enabled"]["external"] is True
