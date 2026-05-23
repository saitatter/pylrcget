from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPalette
from PySide6.QtWidgets import QStyle, QStyledItemDelegate


class LyricsStatusDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        if not option.state & QStyle.StateFlag.State_Selected:
            return

        foreground = index.data(Qt.ItemDataRole.ForegroundRole)
        if foreground is None:
            return

        if isinstance(foreground, QBrush):
            brush = foreground
        elif isinstance(foreground, QColor):
            brush = QBrush(foreground)
        else:
            brush = QBrush(QColor(foreground))

        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
            option.palette.setBrush(group, QPalette.ColorRole.Text, brush)
            option.palette.setBrush(group, QPalette.ColorRole.HighlightedText, brush)