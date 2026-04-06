from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton

from ui.icon_loader import load_svg_pixmap
from ui.spacing import SPACE_2, SPACE_3, SPACE_4, set_layout_spacing
from ui.style_loader import load_stylesheet


class EmptyStateWidget(QWidget):
    actionTriggered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("EmptyState")

        layout = QVBoxLayout(self)
        set_layout_spacing(layout, margins=SPACE_4, spacing=SPACE_2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

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
        self.body.setMaximumWidth(360)

        self.action = QPushButton()
        self.action.setObjectName("EmptyStateAction")
        self.action.clicked.connect(self.actionTriggered.emit)
        self.action.hide()

        layout.addWidget(self.icon)
        layout.addWidget(self.title)
        layout.addWidget(self.body)
        layout.addWidget(self.action, 0, Qt.AlignmentFlag.AlignCenter)

        self.setStyleSheet(load_stylesheet("empty_state.qss"))

    def configure(
        self,
        *,
        icon_name: str,
        title: str,
        body: str,
        action_text: str | None = None,
    ) -> None:
        self.icon.setPixmap(load_svg_pixmap(icon_name, 56))
        self.title.setText(title)
        self.body.setText(body)

        if action_text:
            self.action.setText(action_text)
            self.action.show()
        else:
            self.action.hide()
