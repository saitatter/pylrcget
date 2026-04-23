from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.icon_loader import load_svg_icon
from ui.spacing import SPACE_1, SPACE_2, SPACE_3, set_layout_spacing
from ui.services.download_modes import download_missing_tooltip


class TopBarController(QWidget):
    def __init__(
        self,
        *,
        on_refresh,
        on_download_missing,
        on_open_settings,
        on_open_about,
        on_toggle_logs,
        on_schedule_search,
        on_filter_changed,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("TopBar")

        root = QHBoxLayout(self)
        self.root_layout = root
        set_layout_spacing(root, margins=SPACE_2, spacing=SPACE_2)

        self.search_group = QWidget()
        self.search_group.setObjectName("TopBarGroup")
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
        filters_row.addStretch(1)
        filters_layout.addLayout(filters_row)
        root.addWidget(self.filters_group, stretch=2)

        self.actions_group = QWidget()
        self.actions_group.setObjectName("TopBarGroup")
        actions_layout = QVBoxLayout(self.actions_group)
        set_layout_spacing(actions_layout, margins=SPACE_2, spacing=SPACE_1)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.actions_label = QLabel("Global Actions")
        self.actions_label.setObjectName("TopBarLabel")
        actions_layout.addWidget(self.actions_label)

        actions_row = QHBoxLayout()
        set_layout_spacing(actions_row, spacing=SPACE_2)

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
        self.btn_logs.setIcon(load_svg_icon("logs.svg", 18))
        self.btn_logs.setToolTip("Logs")
        self.btn_logs.setAccessibleName("Toggle log panel")
        self.btn_logs.setCheckable(True)
        self.btn_logs.clicked.connect(on_toggle_logs)

        self.btn_bg_activity = QToolButton()
        self.btn_bg_activity.setObjectName("TopBarAction")
        self.btn_bg_activity.setIcon(load_svg_icon("download.svg", 18))
        self.btn_bg_activity.setToolTip("Background operation in progress — click to view")
        self.btn_bg_activity.setAccessibleName("Show background operation progress")
        self.btn_bg_activity.hide()

        actions_row.addWidget(self.btn_refresh)
        actions_row.addWidget(self.btn_download_missing)
        actions_row.addWidget(self.btn_config)
        actions_row.addWidget(self.btn_about)
        actions_row.addWidget(self.btn_logs)
        actions_row.addWidget(self.btn_bg_activity)
        actions_row.addStretch(1)
        actions_layout.addLayout(actions_row)
        root.addWidget(self.actions_group, stretch=1)

    def _make_action_button(self, icon_name: str, tooltip: str, accessible_name: str, callback) -> QToolButton:
        button = QToolButton()
        button.setObjectName("TopBarAction")
        button.setIcon(load_svg_icon(icon_name, 18))
        button.setToolTip(tooltip)
        button.setAccessibleName(accessible_name)
        button.clicked.connect(callback)
        return button

    def search_text(self) -> str:
        return self.search_box.text()

    def filter_values(self) -> dict[str, bool]:
        return {
            "synced": self.chk_synced.isChecked(),
            "plain": self.chk_plain.isChecked(),
            "instrumental": self.chk_instr.isChecked(),
            "none": self.chk_none.isChecked(),
        }

    def reset_track_filters(self) -> None:
        self.search_box.blockSignals(True)
        self.search_box.setText("")
        self.search_box.blockSignals(False)
        for checkbox, checked in (
            (self.chk_synced, True),
            (self.chk_plain, True),
            (self.chk_instr, False),
            (self.chk_none, True),
        ):
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)

    def clear_library_search(self) -> None:
        self.search_box.blockSignals(True)
        self.search_box.setText("")
        self.search_box.blockSignals(False)

    def set_actions_label(self, text: str) -> None:
        self.actions_label.setText(text)

    def set_download_missing_mode(self, mode: str) -> None:
        tooltip = download_missing_tooltip(mode)
        self.btn_download_missing.setToolTip(tooltip)
        self.btn_download_missing.setStatusTip(tooltip)

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
        else:
            self.root_layout.setDirection(QBoxLayout.LeftToRight)

    def bind_tab_order(self, window, tabs_widget) -> None:
        window.setTabOrder(self.search_box, self.btn_refresh)
        window.setTabOrder(self.btn_refresh, self.btn_config)
        window.setTabOrder(self.btn_config, self.btn_about)
        window.setTabOrder(self.btn_about, tabs_widget)
