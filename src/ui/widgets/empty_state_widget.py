from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from ui.button_roles import set_button_role
from ui.icon_loader import load_svg_pixmap
from ui.spacing import SPACE_2, SPACE_3, SPACE_4, set_layout_spacing
from ui.style_loader import load_stylesheet
from ui.widgets.lyrics_editor_parts import FlowLayout

EMPTY_STATE_BODY_MIN_WIDTH = 360
EMPTY_STATE_BODY_MAX_WIDTH = 560
EMPTY_STATE_BUTTON_MIN_WIDTH = 140


class EmptyStateWidget(QWidget):
    actionTriggered = Signal()
    secondaryActionTriggered = Signal()
    tertiaryActionTriggered = Signal()
    quaternaryActionTriggered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("EmptyState")
        self._content_centered = False

        layout = QVBoxLayout(self)
        set_layout_spacing(layout, margins=(SPACE_4, SPACE_3, SPACE_4, SPACE_3), spacing=SPACE_2)

        self.icon = QLabel()
        self.icon.setObjectName("EmptyStateIcon")
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title = QLabel()
        self.title.setObjectName("EmptyStateTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setWordWrap(True)

        self.body = QLabel()
        self.body.setObjectName("EmptyStateBody")
        self.body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.setWordWrap(True)
        # Keep short empty-state messages from collapsing to their minimum
        # wrapped width (which can clip the second line in a narrow layout).
        self.body.setMinimumWidth(EMPTY_STATE_BODY_MIN_WIDTH)
        self.body.setMaximumWidth(EMPTY_STATE_BODY_MIN_WIDTH)

        self.action = QPushButton()
        self.action.setObjectName("EmptyStateAction")
        set_button_role(self.action, "primary")
        self.action.clicked.connect(self.actionTriggered.emit)
        self.action.hide()

        self.secondary_action = QPushButton()
        self.secondary_action.setObjectName("EmptyStateSecondaryAction")
        set_button_role(self.secondary_action, "secondary")
        self.secondary_action.clicked.connect(self.secondaryActionTriggered.emit)
        self.secondary_action.hide()

        self.tertiary_action = QPushButton()
        self.tertiary_action.setObjectName("EmptyStateTertiaryAction")
        set_button_role(self.tertiary_action, "secondary")
        self.tertiary_action.clicked.connect(self.tertiaryActionTriggered.emit)
        self.tertiary_action.hide()

        self.quaternary_action = QPushButton()
        self.quaternary_action.setObjectName("EmptyStateQuaternaryAction")
        set_button_role(self.quaternary_action, "secondary")
        self.quaternary_action.clicked.connect(self.quaternaryActionTriggered.emit)
        self.quaternary_action.hide()

        self._btn_row = FlowLayout(spacing=SPACE_2, justify_rows=False, center_rows=True)
        self._btn_row.addWidget(self.action)
        self._btn_row.addWidget(self.secondary_action)
        self._btn_row.addWidget(self.tertiary_action)
        self._btn_row.addWidget(self.quaternary_action)

        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.body, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(self._btn_row)
        layout.addStretch(1)

        self._apply_styles()
        self._sync_text_width()

    def configure(
        self,
        *,
        icon_name: str,
        title: str,
        body: str,
        action_text: str | None = None,
        secondary_action_text: str | None = None,
        tertiary_action_text: str | None = None,
        quaternary_action_text: str | None = None,
    ) -> None:
        self.icon.setPixmap(load_svg_pixmap(icon_name, 56))
        self.title.setText(title)
        self.body.setText(body)

        if action_text:
            self.action.setText(action_text)
            self.action.show()
        else:
            self.action.hide()

        if secondary_action_text:
            self.secondary_action.setText(secondary_action_text)
            self.secondary_action.show()
        else:
            self.secondary_action.hide()

        if tertiary_action_text:
            self.tertiary_action.setText(tertiary_action_text)
            self.tertiary_action.show()
        else:
            self.tertiary_action.hide()

        if quaternary_action_text:
            self.quaternary_action.setText(quaternary_action_text)
            self.quaternary_action.show()
        else:
            self.quaternary_action.hide()

        self._sync_text_width()

    def set_content_centered(self, centered: bool) -> None:
        """Center the empty-state group vertically when no actions are needed."""
        centered = bool(centered)
        if centered == self._content_centered:
            return

        layout = self.layout()
        if layout is None:
            return

        if centered:
            layout.insertStretch(0, 1)
        else:
            layout.takeAt(0)
        self._content_centered = centered
        layout.invalidate()
        self.updateGeometry()

    def _sync_text_width(self) -> None:
        visible_buttons = [
            button
            for button in (
                self.action,
                self.secondary_action,
                self.tertiary_action,
                self.quaternary_action,
            )
            if not button.isHidden()
        ]
        preferred_width = (
            len(visible_buttons) * EMPTY_STATE_BUTTON_MIN_WIDTH
            + max(0, len(visible_buttons) - 1) * self._btn_row.spacing()
        )
        max_width = max(
            EMPTY_STATE_BODY_MIN_WIDTH,
            min(EMPTY_STATE_BODY_MAX_WIDTH, preferred_width),
        )
        self.body.setMaximumWidth(max_width)
        self.body.updateGeometry()
        self.updateGeometry()
        layout = self.layout()
        if layout is not None:
            layout.invalidate()

    def _apply_styles(self):
        self.setStyleSheet(load_stylesheet("empty_state.qss"))
