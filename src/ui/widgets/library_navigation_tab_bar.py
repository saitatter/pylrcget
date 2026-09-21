from __future__ import annotations

from PySide6.QtGui import QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QTabBar


class LibraryNavigationTabBar(QTabBar):
    """Flat tab bar with a visual boundary before the LRCLIB destinations."""

    LIBRARY_TAB_COUNT = 4

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)

        if self.count() <= self.LIBRARY_TAB_COUNT:
            return

        library_last = self.tabRect(self.LIBRARY_TAB_COUNT - 1)
        lrclib_first = self.tabRect(self.LIBRARY_TAB_COUNT)
        if not library_last.isValid() or not lrclib_first.isValid():
            return

        separator_x = (library_last.right() + lrclib_first.left()) // 2
        painter = QPainter(self)
        painter.setPen(QPen(self.palette().mid().color(), 1))
        painter.drawLine(separator_x, 8, separator_x, max(8, self.height() - 8))
        painter.end()
