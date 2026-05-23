from __future__ import annotations

import json
from typing import Mapping

AI_SYNC_MODEL_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Tiny (fastest)", "tiny"),
    ("Base (recommended)", "base"),
    ("Small (better accuracy)", "small"),
)

AI_SYNC_DEVICE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Auto", "auto"),
    ("CPU only", "cpu"),
)

_DEFAULT_AI_SYNC_SETTINGS = {
    "whisper_model": "base",
    "device": "auto",
    "use_demucs": True,
}


def load_ai_sync_settings(ui_state_json: str) -> dict[str, object]:
    try:
        state = json.loads(ui_state_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        state = {}
    if not isinstance(state, dict):
        state = {}

    raw = state.get("ai_sync")
    if not isinstance(raw, dict):
        raw = {}

    whisper_model = str(raw.get("whisper_model") or _DEFAULT_AI_SYNC_SETTINGS["whisper_model"])
    valid_models = {value for _label, value in AI_SYNC_MODEL_OPTIONS}
    if whisper_model not in valid_models:
        whisper_model = str(_DEFAULT_AI_SYNC_SETTINGS["whisper_model"])

    device = str(raw.get("device") or _DEFAULT_AI_SYNC_SETTINGS["device"])
    valid_devices = {value for _label, value in AI_SYNC_DEVICE_OPTIONS}
    if device not in valid_devices:
        device = str(_DEFAULT_AI_SYNC_SETTINGS["device"])

    return {
        "whisper_model": whisper_model,
        "device": device,
        "use_demucs": bool(raw.get("use_demucs", _DEFAULT_AI_SYNC_SETTINGS["use_demucs"])),
    }


def merge_ai_sync_settings(ui_state_json: str, settings: Mapping[str, object]) -> str:
    try:
        state = json.loads(ui_state_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        state = {}
    if not isinstance(state, dict):
        state = {}

    normalized = load_ai_sync_settings(json.dumps({"ai_sync": dict(settings)}, ensure_ascii=True))
    state["ai_sync"] = normalized
    return json.dumps(state, ensure_ascii=True, separators=(",", ":"))