from __future__ import annotations

import json

from ui.ai_sync_settings import load_ai_sync_settings, merge_ai_sync_settings


def test_load_ai_sync_settings_defaults_when_missing():
    loaded = load_ai_sync_settings("{}")
    assert loaded["whisper_model"] == "base"
    assert loaded["device"] == "auto"
    assert loaded["language"] == "auto"
    assert loaded["enable_fuzzy"] is True
    assert loaded["fuzzy_threshold"] == 60
    assert loaded["enable_demucs_candidate"] is True


def test_load_ai_sync_settings_coerces_legacy_types():
    state = json.dumps(
        {
            "ai_sync": {
                "device": "cpu",
                "language": "ro",
                "enable_fuzzy": "false",
                "fuzzy_threshold": "72",
                "enable_demucs_candidate": "false",
            }
        }
    )
    loaded = load_ai_sync_settings(state)
    assert loaded["device"] == "cpu"
    assert loaded["language"] == "ro"
    assert loaded["enable_fuzzy"] is False
    assert loaded["fuzzy_threshold"] == 72
    assert loaded["enable_demucs_candidate"] is False


def test_load_ai_sync_settings_clamps_invalid_threshold():
    state = json.dumps({"ai_sync": {"fuzzy_threshold": 999}})
    loaded = load_ai_sync_settings(state)
    assert loaded["fuzzy_threshold"] == 100


def test_merge_ai_sync_settings_preserves_unrelated_ui_state():
    existing = json.dumps({"panel_layout": {"left": 280}, "ai_sync": {"device": "cpu"}})
    merged = merge_ai_sync_settings(
        existing,
        {
            "device": "cuda",
            "language": "en",
            "enable_fuzzy": False,
            "fuzzy_threshold": 70,
            "enable_demucs_candidate": False,
        },
    )
    parsed = json.loads(merged)
    assert parsed["panel_layout"] == {"left": 280}
    assert parsed["ai_sync"]["device"] == "cuda"
    assert parsed["ai_sync"]["language"] == "en"
    assert parsed["ai_sync"]["enable_fuzzy"] is False
    assert parsed["ai_sync"]["fuzzy_threshold"] == 70
    assert parsed["ai_sync"]["enable_demucs_candidate"] is False
