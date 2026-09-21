from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter


class LyricsPaneSplitter(QSplitter):
    """Library/lyrics splitter with a dedicated resize handle."""

    def __init__(self, orientation: Qt.Orientation = Qt.Orientation.Horizontal, parent=None) -> None:
        super().__init__(orientation, parent)
        self.setObjectName("LibraryLyricsSplitter")
        self.setHandleWidth(24)
