from __future__ import annotations

import json
import sys

from lyrics.source_settings import (
    load_lyrics_source_settings,
    merge_lyrics_source_settings,
    parse_helper_command,
)


def test_source_settings_preserve_lrclib_default_and_disable_new_providers():
    settings = load_lyrics_source_settings("")

    assert settings["priority"] == ["lrclib", "tidal"]
    assert settings["enabled"] == {"lrclib": True, "tidal": False}
    assert settings["tidal"] == {
        "country_code": "Auto",
        "transport": "official",
        "client_id": "",
        "redirect_uri": "http://127.0.0.1:8765/callback",
        "helper_command": "",
    }


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

    assert settings["priority"] == ["tidal", "lrclib"]
    assert settings["enabled"]["tidal"] is True
    assert settings["tidal"] == {
        "country_code": "RO",
        "transport": "official",
        "client_id": "",
        "redirect_uri": "http://127.0.0.1:8765/callback",
        "helper_command": "",
    }


def test_source_settings_merge_preserves_unrelated_ui_state():
    merged = merge_lyrics_source_settings(
        json.dumps({"editor_auto_edit_on_add_line": True}),
        {"priority": ["tidal"], "enabled": {"tidal": True}},
    )

    state = json.loads(merged)
    assert state["editor_auto_edit_on_add_line"] is True
    assert state["lyrics_sources"]["enabled"]["tidal"] is True


def test_source_settings_migrate_legacy_external_helper_into_tidal_settings():
    settings = load_lyrics_source_settings(
        json.dumps(
            {
                "lyrics_sources": {
                    "priority": ["external", "lrclib"],
                    "enabled": {"external": True, "lrclib": True},
                    "external": {"helper_command": "python tidal_helper.py"},
                }
            }
        )
    )

    assert settings["priority"] == ["lrclib", "tidal"]
    assert settings["enabled"] == {"lrclib": True, "tidal": False}
    assert settings["tidal"]["helper_command"] == "python tidal_helper.py"
    assert "external" not in settings


def test_parse_helper_command_preserves_windows_argv_without_shell_expansion():
    assert parse_helper_command('python "C:\\Program Files\\helper.py" --mode tidal') == (
        "python",
        "C:\\Program Files\\helper.py",
        "--mode",
        "tidal",
    )
    assert parse_helper_command('python "unterminated') == ()
    assert parse_helper_command("C:\\Tools\\tidal_helper.py") == (
        sys.executable,
        "C:\\Tools\\tidal_helper.py",
    )
