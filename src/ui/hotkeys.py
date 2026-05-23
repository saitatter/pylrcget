from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping

from PySide6.QtGui import QKeySequence


@dataclass(frozen=True)
class HotkeySpec:
    group: str
    label: str
    description: str
    default: str


HOTKEY_SPECS: dict[str, HotkeySpec] = {
    "play_pause": HotkeySpec(
        group="global",
        label="Play / pause",
        description="Toggle playback in the player bar",
        default="Space",
    ),
    "play_next": HotkeySpec(
        group="global",
        label="Play next",
        description="Play the next track in the queue",
        default="Ctrl+Right",
    ),
    "play_previous": HotkeySpec(
        group="global",
        label="Play previous",
        description="Play the previous track in the queue",
        default="Ctrl+Left",
    ),
    "save_lyrics": HotkeySpec(
        group="global",
        label="Save lyrics",
        description="Save lyrics from the active lyrics editor",
        default="Ctrl+S",
    ),
    "focus_search": HotkeySpec(
        group="global",
        label="Focus library search",
        description="Focus the library search box",
        default="Ctrl+F",
    ),
    "clear_search": HotkeySpec(
        group="global",
        label="Clear search",
        description="Clear the search box when it has focus",
        default="Escape",
    ),
    "toggle_hotkey_hints": HotkeySpec(
        group="global",
        label="Toggle shortcut hints",
        description="Show or hide the on-screen shortcut badges",
        default="Ctrl+/",
    ),
    "snap": HotkeySpec(
        group="lyrics",
        label="Snap selected line",
        description="Set the selected line's timestamp to the current playback position",
        default="Ctrl+Enter",
    ),
    "shift_selected": HotkeySpec(
        group="lyrics",
        label="Shift selected lines",
        description="Shift selected lines by the custom amount",
        default="Shift+Enter",
    ),
    "shift_all_from_first": HotkeySpec(
        group="lyrics",
        label="Shift all from first",
        description="Align all lines so the first line matches the current playback position",
        default="Ctrl+Shift+Enter",
    ),
}


def hotkey_specs_for_group(group: str) -> dict[str, HotkeySpec]:
    return {action: spec for action, spec in HOTKEY_SPECS.items() if spec.group == group}


def default_hotkey_bindings() -> dict[str, dict[str, object]]:
    return {
        action: {"enabled": True, "key": spec.default}
        for action, spec in HOTKEY_SPECS.items()
    }


def lyrics_hotkey_defaults() -> dict[str, dict[str, object]]:
    return {
        action: {"enabled": True, "key": spec.default}
        for action, spec in hotkey_specs_for_group("lyrics").items()
    }


def global_hotkey_defaults() -> dict[str, dict[str, object]]:
    return {
        action: {"enabled": True, "key": spec.default}
        for action, spec in hotkey_specs_for_group("global").items()
    }


def normalize_hotkey_text(value: str | None, fallback: str = "") -> str:
    text = (value or "").strip()
    if not text:
        text = fallback.strip()
    if not text:
        return ""
    sequence = QKeySequence.fromString(text, QKeySequence.SequenceFormat.PortableText)
    normalized = sequence.toString(QKeySequence.SequenceFormat.PortableText)
    return normalized or fallback.strip()


def _coerce_enabled(value: object, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"0", "false", "no", "off"}:
            return False
        if lowered in {"1", "true", "yes", "on"}:
            return True
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def parse_hotkey_bindings(payload: str | None) -> dict[str, dict[str, object]]:
    bindings = default_hotkey_bindings()
    if not payload:
        return bindings
    try:
        decoded = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return bindings
    if not isinstance(decoded, dict):
        return bindings
    for action, spec in HOTKEY_SPECS.items():
        raw_value = decoded.get(action)
        if isinstance(raw_value, dict):
            bindings[action] = {
                "enabled": _coerce_enabled(raw_value.get("enabled"), True),
                "key": normalize_hotkey_text(raw_value.get("key"), spec.default),
            }
            continue
        if raw_value is None:
            continue
        bindings[action] = {
            "enabled": True,
            "key": normalize_hotkey_text(str(raw_value), spec.default),
        }
    return bindings


def parse_lyrics_hotkeys(payload: str | None) -> dict[str, dict[str, object]]:
    return {
        action: binding
        for action, binding in parse_hotkey_bindings(payload).items()
        if action in hotkey_specs_for_group("lyrics")
    }


def parse_global_hotkeys(payload: str | None) -> dict[str, dict[str, object]]:
    return {
        action: binding
        for action, binding in parse_hotkey_bindings(payload).items()
        if action in hotkey_specs_for_group("global")
    }


def serialize_hotkey_bindings(bindings: Mapping[str, Mapping[str, object]]) -> str:
    normalized = {
        action: {
            "enabled": _coerce_enabled(bindings.get(action, {}).get("enabled"), True),
            "key": normalize_hotkey_text(bindings.get(action, {}).get("key"), spec.default),
        }
        for action, spec in HOTKEY_SPECS.items()
    }
    return json.dumps(normalized, ensure_ascii=True, separators=(",", ":"))


def serialize_lyrics_hotkeys(bindings: Mapping[str, Mapping[str, object]]) -> str:
    merged = default_hotkey_bindings()
    for action, binding in bindings.items():
        if action in merged:
            if not isinstance(binding, Mapping):
                merged[action] = {
                    "enabled": True,
                    "key": normalize_hotkey_text(str(binding), HOTKEY_SPECS[action].default),
                }
                continue
            merged[action] = {
                "enabled": _coerce_enabled(binding.get("enabled"), True),
                "key": normalize_hotkey_text(binding.get("key"), HOTKEY_SPECS[action].default),
            }
    return serialize_hotkey_bindings(merged)


def effective_hotkey_text(binding: Mapping[str, object] | None, spec: HotkeySpec) -> str:
    if not binding:
        return spec.default
    if not _coerce_enabled(binding.get("enabled"), True):
        return ""
    return normalize_hotkey_text(binding.get("key"), spec.default)


def find_duplicate_hotkeys(bindings: Mapping[str, Mapping[str, object]]) -> list[tuple[str, str, str]]:
    seen: dict[str, str] = {}
    duplicates: list[tuple[str, str, str]] = []
    for action, spec in HOTKEY_SPECS.items():
        value = effective_hotkey_text(bindings.get(action), spec)
        if not value:
            continue
        other = seen.get(value)
        if other is not None:
            duplicates.append((other, action, value))
            continue
        seen[value] = action
    return duplicates