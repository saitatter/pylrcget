from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut

from ui.hotkeys import (
    HOTKEY_SPECS,
    effective_hotkey_text,
    lyrics_hotkey_defaults,
    normalize_hotkey_text,
)


def make_shortcut(widget, key: str, callback) -> QShortcut:
    shortcut = QShortcut(QKeySequence(key), widget.table)
    shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
    shortcut.activated.connect(callback)
    return shortcut


def set_hotkey_bindings(widget, bindings: dict[str, dict[str, object]] | None) -> None:
    normalized = lyrics_hotkey_defaults()
    for action, binding in normalized.items():
        incoming = (bindings or {}).get(action, {})
        if not isinstance(incoming, dict):
            incoming = {"enabled": True, "key": str(incoming)}
        normalized[action] = {
            "enabled": bool(incoming.get("enabled", binding["enabled"])),
            "key": normalize_hotkey_text(str(incoming.get("key", binding["key"])) or "", str(binding["key"])),
        }
    widget._lyrics_hotkeys = normalized
    snap_key = effective_hotkey_text(normalized["snap"], HOTKEY_SPECS["snap"])
    shift_selected_key = effective_hotkey_text(normalized["shift_selected"], HOTKEY_SPECS["shift_selected"])
    shift_all_key = effective_hotkey_text(normalized["shift_all_from_first"], HOTKEY_SPECS["shift_all_from_first"])
    replace_action_shortcuts(
        widget,
        "_shortcut_snap",
        "_shortcut_snap_enter",
        snap_key,
        widget._snap_selected_line_to_current_time,
    )
    replace_action_shortcuts(
        widget,
        "_shortcut_shift_selected",
        "_shortcut_shift_selected_enter",
        shift_selected_key,
        widget._shift_selected_lines_by_custom_amount,
    )
    replace_action_shortcuts(
        widget,
        "_shortcut_shift_all",
        "_shortcut_shift_all_enter",
        shift_all_key,
        widget._shift_all_lines_from_first_delta,
    )
    widget.btn_snap.setToolTip(
        "Set the selected line's timestamp to the current playback position "
        f"({snap_key or 'Disabled'})"
    )
    widget.btn_shift_selected.setToolTip(
        f"Shift selected lines by the custom amount ({shift_selected_key or 'Disabled'})"
    )
    widget.btn_shift_all_from_first.setToolTip(
        "Align all lines so the first line matches the current playback position "
        f"({shift_all_key or 'Disabled'})"
    )


def replace_action_shortcuts(widget, primary_attr: str, secondary_attr: str, key: str, callback) -> None:
    primary, secondary = shortcut_variants(key)
    replace_shortcut(widget, primary_attr, primary, callback)
    replace_shortcut(widget, secondary_attr, secondary, callback)


def replace_shortcut(widget, attr_name: str, key: str | None, callback) -> None:
    existing = getattr(widget, attr_name, None)
    if existing is not None:
        existing.deleteLater()
    if key:
        setattr(widget, attr_name, widget._make_shortcut(key, callback))
        return
    setattr(widget, attr_name, None)


def shortcut_variants(key: str) -> tuple[str, str | None]:
    normalized = normalize_hotkey_text(key)
    if "Enter" in normalized and "Return" not in normalized:
        return normalized.replace("Enter", "Return"), normalized
    if "Return" in normalized and "Enter" not in normalized:
        return normalized, normalized.replace("Return", "Enter")
    return normalized, None