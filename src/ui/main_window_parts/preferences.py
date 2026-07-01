from __future__ import annotations

import json
from dataclasses import replace

from PySide6.QtCore import QByteArray, QRect, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QWidget

from db.queries import get_config, set_config
from ui.app_theme import apply_app_theme
from ui.hotkeys import HOTKEY_SPECS, effective_hotkey_text, parse_hotkey_bindings
from ui.style_loader import load_stylesheet

RESPONSIVE_LAYOUT_BREAKPOINT = 980


def focus_search(window) -> None:
    window.top_bar.search_box.setFocus()
    window.top_bar.search_box.selectAll()


def clear_search(window) -> None:
    if window.top_bar.search_box.hasFocus():
        window.top_bar.search_box.clear()
        window.top_bar.search_box.clearFocus()


def toggle_hotkey_hints(window, feedback_reset_ms: int) -> None:
    visible = window.hotkey_hints.toggle()
    if hasattr(window, "top_bar"):
        window.top_bar.btn_hotkeys.setChecked(visible)
    window._show_status_message(
        "Keyboard shortcut hints shown." if visible else "Keyboard shortcut hints hidden.",
        feedback_reset_ms,
    )


def apply_hotkey_preferences(window, config) -> None:
    bindings = parse_hotkey_bindings(getattr(config, "hotkey_bindings_json", ""))
    window._apply_global_shortcuts(bindings)
    lyrics_hotkeys = {
        action: binding for action, binding in bindings.items() if HOTKEY_SPECS[action].group == "lyrics"
    }
    for view in window._all_lyrics_views():
        view.set_hotkey_bindings(lyrics_hotkeys)
    window._register_hotkey_hints(bindings)
    if getattr(window, "hotkey_hints", None):
        window.hotkey_hints.refresh_positions()


def apply_global_shortcuts(window, bindings: dict[str, dict[str, object]]) -> None:
    handlers = {
        "play_pause": window._toggle_play_pause,
        "play_next": window.play_next,
        "play_previous": window.play_prev,
        "save_lyrics": window._save_active_lyrics,
        "focus_search": window._focus_search,
        "clear_search": window._clear_search,
        "toggle_hotkey_hints": window._toggle_hotkey_hints,
    }
    for action, callback in handlers.items():
        replace_global_shortcut(
            window,
            action,
            effective_hotkey_text(bindings.get(action), HOTKEY_SPECS[action]),
            callback,
        )


def replace_global_shortcut(window, action: str, key: str, callback) -> None:
    if not hasattr(window, "_global_shortcuts"):
        window._global_shortcuts = {}
    existing = window._global_shortcuts.get(action)
    if existing is not None:
        existing.deleteLater()
        window._global_shortcuts[action] = None
    if not key:
        return
    shortcut = QShortcut(QKeySequence(key), window)
    shortcut.activated.connect(callback)
    window._global_shortcuts[action] = shortcut


def register_hotkey_hints(window, bindings: dict[str, dict[str, object]] | None = None) -> None:
    bindings = bindings or parse_hotkey_bindings(get_config(window.app_state.db).hotkey_bindings_json)
    window.hotkey_hints.register(
        window.top_bar.search_box,
        effective_hotkey_text(bindings.get("focus_search"), HOTKEY_SPECS["focus_search"]),
    )
    window.hotkey_hints.register(
        window.top_bar.btn_hotkeys,
        effective_hotkey_text(bindings.get("toggle_hotkey_hints"), HOTKEY_SPECS["toggle_hotkey_hints"]),
    )
    window.hotkey_hints.register(window.track_list.table, "Enter")
    for view in window._all_lyrics_views():
        window.hotkey_hints.register(view.btn_snap, effective_hotkey_text(bindings.get("snap"), HOTKEY_SPECS["snap"]))
        window.hotkey_hints.register(view.btn_shift_minus, "Left")
        window.hotkey_hints.register(view.btn_shift_plus, "Right")
        window.hotkey_hints.register(
            view.btn_shift_selected,
            effective_hotkey_text(bindings.get("shift_selected"), HOTKEY_SPECS["shift_selected"]),
        )
        window.hotkey_hints.register(
            view.btn_shift_all_from_first,
            effective_hotkey_text(bindings.get("shift_all_from_first"), HOTKEY_SPECS["shift_all_from_first"]),
        )
        window.hotkey_hints.register(view.btn_add, "Ctrl+N")
        window.hotkey_hints.register(view.btn_del, "Delete")
        window.hotkey_hints.register(
            view.btn_save,
            effective_hotkey_text(bindings.get("save_lyrics"), HOTKEY_SPECS["save_lyrics"]),
        )
    window.hotkey_hints.register(
        window.player_bar.btn_prev,
        effective_hotkey_text(bindings.get("play_previous"), HOTKEY_SPECS["play_previous"]),
    )
    window.hotkey_hints.register(
        window.player_bar.btn_play,
        effective_hotkey_text(bindings.get("play_pause"), HOTKEY_SPECS["play_pause"]),
    )
    window.hotkey_hints.register(
        window.player_bar.btn_next,
        effective_hotkey_text(bindings.get("play_next"), HOTKEY_SPECS["play_next"]),
    )


def reset_refresh_feedback(window) -> None:
    window.top_bar.reset_refresh_feedback(window._refresh_default_label)


def update_responsive_layout(window) -> None:
    width = max(0, window.width())
    window.top_bar.update_responsive_layout(width)

    if hasattr(window, "content_splitter"):
        if width < RESPONSIVE_LAYOUT_BREAKPOINT:
            if window.content_splitter.orientation() != Qt.Orientation.Vertical:
                window.content_splitter.setOrientation(Qt.Orientation.Vertical)
                window.content_splitter.setSizes([int(window.height() * 0.54), int(window.height() * 0.46)])
        else:
            if window.content_splitter.orientation() != Qt.Orientation.Horizontal:
                window.content_splitter.setOrientation(Qt.Orientation.Horizontal)
                window.content_splitter.setSizes([int(width * 0.58), int(width * 0.42)])

    for splitter_name in ("albums_splitter", "artists_splitter"):
        splitter = getattr(window, splitter_name, None)
        if splitter is None:
            continue
        if width < RESPONSIVE_LAYOUT_BREAKPOINT:
            if splitter.orientation() != Qt.Orientation.Vertical:
                splitter.setOrientation(Qt.Orientation.Vertical)
                splitter.setSizes([int(window.height() * 0.54), int(window.height() * 0.46)])
        else:
            if splitter.orientation() != Qt.Orientation.Horizontal:
                splitter.setOrientation(Qt.Orientation.Horizontal)
                splitter.setSizes([int(width * 0.58), int(width * 0.42)])

    if hasattr(window, "player_bar"):
        window.player_bar.set_compact_mode(width < RESPONSIVE_LAYOUT_BREAKPOINT)


def save_window_state(window) -> None:
    window._persist_window_state_payload(window._build_window_state_payload())


def build_window_state_payload(window) -> dict[str, object]:
    saved_rect = window.normalGeometry() if window.isMaximized() else window.geometry()
    state: dict[str, object] = {
        "geometry": bytes(window.saveGeometry().toBase64()).decode("ascii"),
        "window_rect": {
            "x": int(saved_rect.x()),
            "y": int(saved_rect.y()),
            "width": int(saved_rect.width()),
            "height": int(saved_rect.height()),
        },
        "is_maximized": bool(window.isMaximized()),
        "tab_index": window.tabs.currentIndex(),
    }
    if hasattr(window, "_build_library_splitter_state"):
        state["library_splitter"] = window._build_library_splitter_state()
    if hasattr(window, "content_splitter"):
        state["tracks_splitter"] = window.content_splitter.sizes()
    if hasattr(window, "albums_splitter"):
        state["albums_splitter"] = window.albums_splitter.sizes()
    if hasattr(window, "artists_splitter"):
        state["artists_splitter"] = window.artists_splitter.sizes()
    if hasattr(window, "top_bar"):
        state["search_text"] = window.top_bar.search_text()
        state["filters"] = {key: bool(value) for key, value in window.top_bar.filter_values().items()}
    return state


def persist_window_state_payload(window, state: dict[str, object]) -> None:
    config = get_config(window.app_state.db)
    try:
        existing_state = json.loads(config.ui_state_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        existing_state = {}
    if not isinstance(existing_state, dict):
        existing_state = {}
    merged_state = dict(existing_state)
    merged_state.update(state)
    set_config(
        window.app_state.db,
        replace(config, ui_state_json=json.dumps(merged_state, ensure_ascii=True, separators=(",", ":"))),
    )


def _window_geometry_is_reasonable(window, rect: QRect, available: QRect | None) -> bool:
    min_width = max(window.minimumWidth(), window.minimumSizeHint().width(), RESPONSIVE_LAYOUT_BREAKPOINT)
    min_height = max(window.minimumHeight(), window.minimumSizeHint().height())
    if rect.width() < min_width or rect.height() < min_height:
        return False
    if available is None:
        return True
    return rect.width() <= available.width() and rect.height() <= available.height()


def _screen_available_geometry(window) -> QRect | None:
    screen = window.screen() if hasattr(window, "screen") else None
    if screen is None:
        screen = QApplication.primaryScreen()
    return screen.availableGeometry() if screen is not None else None


def _rect_from_state_payload(state: dict[str, object]) -> QRect | None:
    raw_rect = state.get("window_rect")
    if isinstance(raw_rect, dict):
        try:
            x = int(raw_rect.get("x", 0))
            y = int(raw_rect.get("y", 0))
            width = int(raw_rect.get("width", 0))
            height = int(raw_rect.get("height", 0))
        except (TypeError, ValueError):
            pass
        else:
            if width > 0 and height > 0:
                return QRect(x, y, width, height)

    geometry = state.get("geometry")
    if isinstance(geometry, str) and geometry:
        restored = QByteArray.fromBase64(geometry.encode("ascii"))
        if not restored.isEmpty():
            probe = QWidget()
            if probe.restoreGeometry(restored):
                return QRect(probe.geometry())

    return None


def _sanitize_restored_window_geometry(window, fallback_geometry: QRect) -> None:
    if window.isMaximized() or window.isFullScreen():
        return

    available = _screen_available_geometry(window)
    current = window.geometry()
    if not _window_geometry_is_reasonable(window, current, available):
        window.setGeometry(fallback_geometry)
        current = window.geometry()

    if available is None:
        return

    max_x = available.x() + max(0, available.width() - current.width())
    max_y = available.y() + max(0, available.height() - current.height())
    target_x = min(max(current.x(), available.x()), max_x)
    target_y = min(max(current.y(), available.y()), max_y)
    if target_x != current.x() or target_y != current.y():
        window.move(target_x, target_y)


def restore_window_state(window) -> None:
    state = window._load_window_state_payload()

    fallback_geometry = QRect(window.geometry())
    restored_rect = _rect_from_state_payload(state)
    if restored_rect is not None:
        window.setGeometry(restored_rect)
        _sanitize_restored_window_geometry(window, fallback_geometry)
    if bool(state.get("is_maximized")) and hasattr(window, "showMaximized"):
        window.showMaximized()

    search_text = state.get("search_text")
    if search_text is not None:
        window.top_bar.set_search_text(str(search_text))

    restored_filters = state.get("filters") if isinstance(state.get("filters"), dict) else {}
    if restored_filters or search_text is not None:
        window.top_bar.set_filter_values(restored_filters)
        window._apply_track_filters()

    if hasattr(window, "_restore_library_splitter_state"):
        window._restore_library_splitter_state(state)

    tab_index = state.get("tab_index")
    if tab_index is not None:
        try:
            idx = int(tab_index)
            if 0 <= idx < window.tabs.count():
                window.tabs.setCurrentIndex(idx)
        except (TypeError, ValueError):
            pass


def load_window_state_payload(window) -> dict[str, object]:
    config = get_config(window.app_state.db)
    try:
        state = json.loads(config.ui_state_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        state = {}
    return state if isinstance(state, dict) else {}


def apply_styles(window) -> None:
    window.setStyleSheet(load_stylesheet("main_window.qss"))


def appearance_scale(ui_scale_percent: int) -> float:
    return max(0.85, min(1.5, float(int(ui_scale_percent or 100)) / 100.0))


def apply_appearance_preferences(window, config) -> None:
    app = QApplication.instance()
    if app is not None:
        apply_app_theme(
            app,
            config.theme_mode,
            ui_scale_percent=config.ui_scale_percent,
            font_size_mode=config.font_size_mode,
        )

    scale = appearance_scale(config.ui_scale_percent)
    if hasattr(window, "player_bar"):
        window.player_bar.set_show_album_art(bool(config.show_album_art))
        window.player_bar.set_ui_scale(scale)
    if hasattr(window, "track_list"):
        window.track_list.set_ui_scale(scale)
    if hasattr(window, "albums_tab"):
        window.albums_tab.set_ui_scale(scale)
    if hasattr(window, "artists_tab"):
        window.artists_tab.set_ui_scale(scale)
    for view in window._all_lyrics_views():
        view.set_ui_scale(scale)