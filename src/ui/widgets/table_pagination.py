from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget


class TablePaginationBar(QWidget):
    """Compact previous/page/next controls for indexed table pages."""

    previousRequested = Signal()
    nextRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TablePaginationBar")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)
        layout.addStretch(1)

        self.previous_button = QPushButton("‹")
        self.previous_button.setObjectName("TablePaginationPrevious")
        self.previous_button.setToolTip("Previous page")
        self.previous_button.setAccessibleName("Previous page")
        self.previous_button.setFixedWidth(32)
        self.previous_button.clicked.connect(self.previousRequested.emit)
        layout.addWidget(self.previous_button)

        self.page_label = QLabel("Page 1")
        self.page_label.setObjectName("TablePaginationLabel")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setMinimumWidth(72)
        layout.addWidget(self.page_label)

        self.next_button = QPushButton("›")
        self.next_button.setObjectName("TablePaginationNext")
        self.next_button.setToolTip("Next page")
        self.next_button.setAccessibleName("Next page")
        self.next_button.setFixedWidth(32)
        self.next_button.clicked.connect(self.nextRequested.emit)
        layout.addWidget(self.next_button)

        layout.addStretch(1)
        self.set_page_state(page=0, has_next=False, visible=False)

    def set_page_state(self, *, page: int, has_next: bool, visible: bool) -> None:
        page_number = max(0, int(page))
        self.page_label.setText(f"Page {page_number + 1}")
        self.previous_button.setEnabled(page_number > 0)
        self.next_button.setEnabled(bool(has_next))
        self.setVisible(bool(visible))
