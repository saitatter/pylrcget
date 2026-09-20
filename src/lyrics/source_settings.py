from __future__ import annotations

import json
import re
from collections.abc import Mapping

LYRICS_SOURCE_IDS: tuple[str, ...] = ("lrclib", "tidal")
LYRICS_SOURCE_LABELS: dict[str, str] = {
    "lrclib": "LRCLIB",
    "tidal": "TIDAL",
}
_COUNTRY_CODE_RE = re.compile(r"^[A-Za-z]{2}$")
TIDAL_DEFAULT_CLIENT_ID = "vJElJOz4TVV3SBnC"
TIDAL_DEFAULT_REDIRECT_URI = "http://127.0.0.1:8765/callback"


def default_lyrics_source_settings() -> dict[str, object]:
    return {
        "priority": list(LYRICS_SOURCE_IDS),
        "enabled": {"lrclib": True, "tidal": False},
        "continue_when_plain_for_synced": True,
        "tidal": {
            "country_code": "Auto",
            "transport": "official",
            "client_id": TIDAL_DEFAULT_CLIENT_ID,
            "redirect_uri": TIDAL_DEFAULT_REDIRECT_URI,
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
    raw_tidal = raw.get("tidal")
    raw_tidal = raw_tidal if isinstance(raw_tidal, Mapping) else {}
    country_code = str(raw_tidal.get("country_code") or "Auto").strip()
    if country_code.casefold() == "auto" or not _COUNTRY_CODE_RE.fullmatch(country_code):
        country_code = "Auto"
    else:
        country_code = country_code.upper()
    client_id = str(raw_tidal.get("client_id") or TIDAL_DEFAULT_CLIENT_ID).strip()
    redirect_uri = str(raw_tidal.get("redirect_uri") or TIDAL_DEFAULT_REDIRECT_URI).strip()

    return {
        "priority": priority,
        "enabled": enabled,
        "continue_when_plain_for_synced": _coerce_bool(
            raw.get("continue_when_plain_for_synced"),
            bool(defaults["continue_when_plain_for_synced"]),
        ),
        "tidal": {
            "country_code": country_code,
            "transport": "official",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
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
