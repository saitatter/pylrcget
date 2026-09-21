from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QSplitter, QSplitterHandle, QToolButton


class _LyricsSplitterHandle(QSplitterHandle):
    def __init__(self, orientation: Qt.Orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
        self.toggle_button = QToolButton(self)
        self.toggle_button.setObjectName("LyricsPaneToggle")
        self.toggle_button.setAutoRaise(True)
        self.toggle_button.setText("›")
        self.toggle_button.setToolTip("Collapse lyrics panel")
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        button_size = min(28, max(20, self.width() - 2), max(20, self.height() - 2))
        self.toggle_button.setGeometry(
            (self.width() - button_size) // 2,
            (self.height() - button_size) // 2,
            button_size,
            button_size,
        )


class LyricsPaneSplitter(QSplitter):
    """Splitter with an explicit, reversible lyrics-pane toggle affordance."""

    toggleRequested = Signal()

    def __init__(self, orientation: Qt.Orientation = Qt.Orientation.Horizontal, parent=None) -> None:
        super().__init__(orientation, parent)
        self.setObjectName("LibraryLyricsSplitter")
        self.setHandleWidth(32)

    def createHandle(self) -> QSplitterHandle:
        handle = _LyricsSplitterHandle(self.orientation(), self)
        handle.toggle_button.clicked.connect(self.toggleRequested.emit)
        return handle

    def set_lyrics_collapsed(self, collapsed: bool) -> None:
        handle = self.handle(1)
        if handle is None:
            return
        button = getattr(handle, "toggle_button", None)
        if button is None:
            return
        collapsed = bool(collapsed)
        button.setText("‹" if collapsed else "›")
        button.setToolTip("Expand lyrics panel" if collapsed else "Collapse lyrics panel")
