from __future__ import annotations

import json
from collections.abc import Mapping

LYRICS_SOURCE_IDS: tuple[str, ...] = ("lrclib", "musixmatch")
LYRICS_SOURCE_LABELS: dict[str, str] = {
    "lrclib": "LRCLIB",
    "musixmatch": "Musixmatch",
}
MUSIXMATCH_DEFAULT_MODE = "website"


def default_lyrics_source_settings() -> dict[str, object]:
    return {
        "priority": list(LYRICS_SOURCE_IDS),
        "enabled": {"lrclib": True, "musixmatch": False},
        "continue_when_plain_for_synced": True,
        "musixmatch": {
            "mode": MUSIXMATCH_DEFAULT_MODE,
            "api_key": "",
        },
    }


def load_lyrics_source_settings(ui_state_json: str | None) -> dict[str, object]:
    try:
        state = json.loads(ui_state_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    raw = state.get("lyrics_sources")
    return normalize_lyrics_source_settings(raw if isinstance(raw, Mapping) else None)


def normalize_lyrics_source_settings(raw: Mapping[str, object] | None) -> dict[str, object]:
    defaults = default_lyrics_source_settings()
    raw = raw or {}

    priority: list[str] = []
    raw_priority = raw.get("priority")
    if isinstance(raw_priority, list):
        for value in raw_priority:
            provider_id = str(value).strip().casefold()
            if provider_id in LYRICS_SOURCE_IDS and provider_id not in priority:
                priority.append(provider_id)
    for provider_id in LYRICS_SOURCE_IDS:
        if provider_id not in priority:
            priority.append(provider_id)

    raw_enabled = raw.get("enabled")
    raw_enabled = raw_enabled if isinstance(raw_enabled, Mapping) else {}
    enabled = {
        provider_id: _coerce_bool(raw_enabled.get(provider_id), bool(defaults["enabled"][provider_id]))
        for provider_id in LYRICS_SOURCE_IDS
    }
    raw_musixmatch = raw.get("musixmatch")
    raw_musixmatch = raw_musixmatch if isinstance(raw_musixmatch, Mapping) else {}
    mode = str(raw_musixmatch.get("mode") or MUSIXMATCH_DEFAULT_MODE).strip().casefold()
    if mode == "desktop":
        mode = MUSIXMATCH_DEFAULT_MODE
    if mode not in {"website", "official"}:
        mode = MUSIXMATCH_DEFAULT_MODE
    api_key = str(raw_musixmatch.get("api_key") or "").strip()

    return {
        "priority": priority,
        "enabled": enabled,
        "continue_when_plain_for_synced": _coerce_bool(
            raw.get("continue_when_plain_for_synced"),
            bool(defaults["continue_when_plain_for_synced"]),
        ),
        "musixmatch": {
            "mode": mode,
            "api_key": api_key,
        },
    }


def merge_lyrics_source_settings(
    ui_state_json: str | None,
    settings: Mapping[str, object],
) -> str:
    try:
        state = json.loads(ui_state_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    normalized = normalize_lyrics_source_settings(settings)
    state["lyrics_sources"] = normalized
    return json.dumps(state, ensure_ascii=True, separators=(",", ":"))


def _coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return default
