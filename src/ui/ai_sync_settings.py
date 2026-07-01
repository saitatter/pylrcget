from __future__ import annotations

import json
from typing import Mapping

AI_SYNC_DEVICE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Auto", "auto"),
    ("CPU only", "cpu"),
    ("GPU (CUDA)", "cuda"),
)

_AI_SYNC_LANGUAGE_CODES: tuple[str, ...] = (
    "af", "am", "ar", "as", "az", "ba", "be", "bg", "bn", "bo", "br", "bs",
    "ca", "cs", "cy", "da", "de", "el", "en", "es", "et", "eu", "fa", "fi",
    "fo", "fr", "gl", "gu", "ha", "haw", "he", "hi", "hr", "ht", "hu", "hy",
    "id", "is", "it", "ja", "jw", "ka", "kk", "km", "kn", "ko", "la", "lb",
    "ln", "lo", "lt", "lv", "mg", "mi", "mk", "ml", "mn", "mr", "ms", "mt",
    "my", "ne", "nl", "nn", "no", "oc", "pa", "pl", "ps", "pt", "ro", "ru",
    "sa", "sd", "si", "sk", "sl", "sn", "so", "sq", "sr", "su", "sv", "sw",
    "ta", "te", "tg", "th", "tk", "tl", "tr", "tt", "uk", "ur", "uz", "vi",
    "yi", "yo", "zh", "yue",
)

AI_SYNC_LANGUAGE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Auto detect", "auto"),
    *tuple((code.upper(), code) for code in _AI_SYNC_LANGUAGE_CODES),
)

_DEFAULT_AI_SYNC_SETTINGS = {
    "whisper_model": "base",
    "device": "auto",
    "language": "auto",
    "enable_fuzzy": True,
    "fuzzy_threshold": 60,
}


def _coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return default


def _coerce_int(value: object, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


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

    device = str(raw.get("device") or _DEFAULT_AI_SYNC_SETTINGS["device"])
    valid_devices = {value for _label, value in AI_SYNC_DEVICE_OPTIONS}
    if device not in valid_devices:
        device = str(_DEFAULT_AI_SYNC_SETTINGS["device"])

    language = str(raw.get("language") or _DEFAULT_AI_SYNC_SETTINGS["language"]).lower()
    valid_languages = {value for _label, value in AI_SYNC_LANGUAGE_OPTIONS}
    if language not in valid_languages:
        language = str(_DEFAULT_AI_SYNC_SETTINGS["language"])

    return {
        "whisper_model": "base",
        "device": device,
        "language": language,
        "enable_fuzzy": _coerce_bool(
            raw.get("enable_fuzzy", _DEFAULT_AI_SYNC_SETTINGS["enable_fuzzy"]),
            bool(_DEFAULT_AI_SYNC_SETTINGS["enable_fuzzy"]),
        ),
        "fuzzy_threshold": _coerce_int(
            raw.get("fuzzy_threshold", _DEFAULT_AI_SYNC_SETTINGS["fuzzy_threshold"]),
            int(_DEFAULT_AI_SYNC_SETTINGS["fuzzy_threshold"]),
            minimum=0,
            maximum=100,
        ),
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