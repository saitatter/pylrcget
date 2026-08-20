from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.icon_loader import load_svg_icon
from ui.services.download_modes import download_missing_tooltip
from ui.spacing import SPACE_1, SPACE_2, SPACE_3, set_layout_spacing


class TopBarController(QWidget):
    _DEFAULT_FILTERS = {
        "synced": True,
        "plain": True,
        "instrumental": False,
        "none": True,
        "unsaved": False,
    }

    def __init__(
        self,
        *,
        on_refresh,
        on_download_missing,
        on_export_library,
        on_open_settings,
        on_open_about,
        on_toggle_logs,
        on_toggle_hotkey_hints,
        on_schedule_search,
        on_filter_changed,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("TopBar")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        root = QHBoxLayout(self)
        self.root_layout = root
        set_layout_spacing(root, margins=SPACE_2, spacing=SPACE_2)

        self.search_group = QWidget()
        self.search_group.setObjectName("TopBarGroup")
        self.search_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        search_layout = QVBoxLayout(self.search_group)
        set_layout_spacing(search_layout, margins=SPACE_2, spacing=SPACE_1)
        search_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.search_label = QLabel("Search Library")
        self.search_label.setObjectName("TopBarLabel")
        search_layout.addWidget(self.search_label)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search tracks / artists / albums...")
        self.search_box.setObjectName("TopBarSearch")
        self.search_box.setAccessibleName("Library search")
        self.search_box.textChanged.connect(on_schedule_search)
        search_layout.addWidget(self.search_box)
        root.addWidget(self.search_group, stretch=3)

        self.filters_group = QWidget()
        self.filters_group.setObjectName("TopBarGroup")
        self.filters_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        filters_layout = QVBoxLayout(self.filters_group)
        set_layout_spacing(filters_layout, margins=SPACE_2, spacing=SPACE_1)
        filters_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.filters_label = QLabel("Filter Lyrics")
        self.filters_label.setObjectName("TopBarLabel")
        filters_layout.addWidget(self.filters_label)

        filters_row = QHBoxLayout()
        set_layout_spacing(filters_row, margins=(0, SPACE_3, 0, 0), spacing=SPACE_2)

        self.chk_synced = QCheckBox("Synced")
        self.chk_synced.setObjectName("TopBarFilterCheck")
        self.chk_synced.setChecked(True)
        self.chk_synced.setAccessibleName("Filter synced lyrics")
        self.chk_synced.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.chk_synced.setMinimumHeight(36)
        self.chk_synced.toggled.connect(on_filter_changed)
        filters_row.addWidget(self.chk_synced)

        self.chk_plain = QCheckBox("Plain")
        self.chk_plain.setObjectName("TopBarFilterCheck")
        self.chk_plain.setChecked(True)
        self.chk_plain.setAccessibleName("Filter plain lyrics")
        self.chk_plain.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.chk_plain.setMinimumHeight(36)
        self.chk_plain.toggled.connect(on_filter_changed)
        filters_row.addWidget(self.chk_plain)

        self.chk_instr = QCheckBox("Instrumental")
        self.chk_instr.setObjectName("TopBarFilterCheck")
        self.chk_instr.setChecked(False)
        self.chk_instr.setAccessibleName("Filter instrumental tracks")
        self.chk_instr.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.chk_instr.setMinimumHeight(36)
        self.chk_instr.toggled.connect(on_filter_changed)
        filters_row.addWidget(self.chk_instr)

        self.chk_none = QCheckBox("No lyrics")
        self.chk_none.setObjectName("TopBarFilterCheck")
        self.chk_none.setChecked(True)
        self.chk_none.setAccessibleName("Filter tracks without lyrics")
        self.chk_none.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.chk_none.setMinimumHeight(36)
        self.chk_none.toggled.connect(on_filter_changed)
        filters_row.addWidget(self.chk_none)

        self.chk_unsaved = QCheckBox("Unsaved")
        self.chk_unsaved.setObjectName("TopBarFilterCheck")
        self.chk_unsaved.setChecked(False)
        self.chk_unsaved.setAccessibleName("Filter tracks with unsaved draft")
        self.chk_unsaved.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.chk_unsaved.setMinimumHeight(36)
        self.chk_unsaved.toggled.connect(on_filter_changed)
        filters_row.addWidget(self.chk_unsaved)

        filters_row.addStretch(1)
        filters_layout.addLayout(filters_row)
        root.addWidget(self.filters_group, stretch=2)

        self.actions_group = QWidget()
        self.actions_group.setObjectName("TopBarGroup")
        self.actions_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        actions_layout = QVBoxLayout(self.actions_group)
        set_layout_spacing(actions_layout, margins=SPACE_2, spacing=SPACE_1)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.actions_label = QLabel("Global Actions")
        self.actions_label.setObjectName("TopBarLabel")
        actions_layout.addWidget(self.actions_label)

        actions_row = QHBoxLayout()
        set_layout_spacing(actions_row, spacing=SPACE_2)
        self._action_icons: dict[QToolButton, str] = {}

        self.btn_refresh = self._make_action_button(
            "refresh-cw.svg",
            "Refresh library",
            "Refresh library",
            on_refresh,
        )
        self.btn_download_missing = self._make_action_button(
            "download.svg",
            "Download missing lyrics",
            "Download missing lyrics",
            on_download_missing,
        )
        self.btn_export_library = self._make_action_button(
            "export.svg",
            "Export lyrics",
            "Export lyrics",
            on_export_library,
        )
        self.btn_export_library.setText("")
        self.btn_export_library.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_config = self._make_action_button(
            "settings-2.svg",
            "Settings",
            "Open music folder settings",
            on_open_settings,
        )
        self.btn_about = self._make_action_button(
            "info.svg",
            "About",
            "About PyLrcGet",
            on_open_about,
        )

        self.btn_logs = QToolButton()
        self.btn_logs.setObjectName("TopBarAction")
        self._set_action_icon(self.btn_logs, "logs.svg")
        self.btn_logs.setToolTip("Logs")
        self.btn_logs.setAccessibleName("Toggle log panel")
        self.btn_logs.setCheckable(True)
        self.btn_logs.clicked.connect(on_toggle_logs)

        self.btn_hotkeys = QToolButton()
        self.btn_hotkeys.setObjectName("TopBarAction")
        self.btn_hotkeys.setText("Keys")
        self.btn_hotkeys.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.btn_hotkeys.setToolTip("Show keyboard shortcut hints")
        self.btn_hotkeys.setAccessibleName("Show keyboard shortcut hints")
        self.btn_hotkeys.setCheckable(True)
        self.btn_hotkeys.clicked.connect(on_toggle_hotkey_hints)

        self.btn_bg_activity = QToolButton()
        self.btn_bg_activity.setObjectName("TopBarAction")
        self._set_action_icon(self.btn_bg_activity, "download.svg")
        self.btn_bg_activity.setToolTip("Background operation in progress — click to view")
        self.btn_bg_activity.setAccessibleName("Show background operation progress")
        self.btn_bg_activity.hide()

        actions_row.addWidget(self.btn_refresh)
        actions_row.addWidget(self.btn_download_missing)
        actions_row.addWidget(self.btn_export_library)
        actions_row.addWidget(self.btn_config)
        actions_row.addWidget(self.btn_about)
        actions_row.addWidget(self.btn_logs)
        actions_row.addWidget(self.btn_hotkeys)
        actions_row.addWidget(self.btn_bg_activity)
        actions_row.addStretch(1)
        actions_layout.addLayout(actions_row)
        root.addWidget(self.actions_group, stretch=1)

    def _make_action_button(self, icon_name: str, tooltip: str, accessible_name: str, callback) -> QToolButton:
        button = QToolButton()
        button.setObjectName("TopBarAction")
        self._set_action_icon(button, icon_name)
        button.setToolTip(tooltip)
        button.setAccessibleName(accessible_name)
        button.clicked.connect(callback)
        return button

    def _set_action_icon(self, button: QToolButton, icon_name: str) -> None:
        self._action_icons[button] = icon_name
        button.setIcon(load_svg_icon(icon_name, 18))

    def refresh_theme_icons(self) -> None:
        for button, icon_name in self._action_icons.items():
            button.setIcon(load_svg_icon(icon_name, 18))

    def apply_current_palette(self) -> None:
        self.refresh_theme_icons()
        self.update()

    def search_text(self) -> str:
        return self.search_box.text()

    def set_search_text(self, text: str) -> None:
        self.search_box.blockSignals(True)
        self.search_box.setText(text or "")
        self.search_box.blockSignals(False)

    def filter_values(self) -> dict[str, bool]:
        return {
            "synced": self.chk_synced.isChecked(),
            "plain": self.chk_plain.isChecked(),
            "instrumental": self.chk_instr.isChecked(),
            "none": self.chk_none.isChecked(),
            "unsaved": self.chk_unsaved.isChecked(),
        }

    @classmethod
    def default_filter_values(cls) -> dict[str, bool]:
        return dict(cls._DEFAULT_FILTERS)

    @staticmethod
    def _coerce_bool(value, default: bool) -> bool:
        if value is None:
            return bool(default)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return bool(default)

    def set_filter_values(self, values: dict[str, object]) -> None:
        merged = self.default_filter_values()
        merged.update(values or {})
        for checkbox, key in (
            (self.chk_synced, "synced"),
            (self.chk_plain, "plain"),
            (self.chk_instr, "instrumental"),
            (self.chk_none, "none"),
            (self.chk_unsaved, "unsaved"),
        ):
            checkbox.blockSignals(True)
            checkbox.setChecked(self._coerce_bool(merged.get(key), self._DEFAULT_FILTERS[key]))
            checkbox.blockSignals(False)

    def reset_track_filters(self) -> None:
        self.set_search_text("")
        self.set_filter_values(self.default_filter_values())

    def clear_library_search(self) -> None:
        self.set_search_text("")

    def set_actions_label(self, text: str) -> None:
        self.actions_label.setText(text)

    def set_download_missing_mode(self, mode: str) -> None:
        tooltip = download_missing_tooltip(mode)
        self.btn_download_missing.setToolTip(tooltip)

    def set_logs_checked(self, checked: bool) -> None:
        self.btn_logs.setChecked(bool(checked))

    def set_button_feedback(self, button: QToolButton, state: str) -> None:
        button.setProperty("actionState", state if state != "idle" else "")
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()
        button.setEnabled(state != "loading")

    def reset_refresh_feedback(self, default_label: str) -> None:
        self.set_button_feedback(self.btn_refresh, "idle")
        self.btn_refresh.setEnabled(True)
        self.actions_label.setText(default_label)

    def update_responsive_layout(self, width: int) -> None:
        if width < 1120:
            self.root_layout.setDirection(QBoxLayout.TopToBottom)
            self.root_layout.setStretch(0, 0)
            self.root_layout.setStretch(1, 0)
            self.root_layout.setStretch(2, 0)
        else:
            self.root_layout.setDirection(QBoxLayout.LeftToRight)
            self.root_layout.setStretch(0, 3)
            self.root_layout.setStretch(1, 2)
            self.root_layout.setStretch(2, 1)
        self.updateGeometry()

    def bind_tab_order(self, window, tabs_widget) -> None:
        window.setTabOrder(self.search_box, self.btn_refresh)
        window.setTabOrder(self.btn_refresh, self.btn_config)
        window.setTabOrder(self.btn_config, self.btn_about)
        window.setTabOrder(self.btn_about, tabs_widget)
