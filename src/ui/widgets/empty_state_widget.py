from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton

from ui.spacing import SPACE_2, SPACE_3, SPACE_4, set_layout_spacing
from ui.style_loader import asset_path, load_stylesheet


def _svg_pixmap(path: Path, size: int = 56) -> QPixmap:
    renderer = QSvgRenderer(str(path))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


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
        self.icon.setPixmap(_svg_pixmap(asset_path("assets", "icons", icon_name)))
        self.title.setText(title)
        self.body.setText(body)

        if action_text:
            self.action.setText(action_text)
            self.action.show()
        else:
            self.action.hide()
