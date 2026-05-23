from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import QLayout

from ui.spacing import SPACE_2


class FlowLayout(QLayout):
    def __init__(self, parent=None, *, spacing: int = SPACE_2, justify_rows: bool = True):
        super().__init__(parent)
        self._items = []
        self._justify_rows = bool(justify_rows)
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def minimumHeightForWidth(self, width: int) -> int:
        return self.heightForWidth(width)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        y = effective.y()
        spacing = self.spacing()
        rows = []
        row = []
        row_width = 0
        row_height = 0

        for item in self._items:
            widget = item.widget()
            if widget is not None and not widget.isVisible():
                continue
            item_size = item.sizeHint()
            next_width = row_width + (spacing if row else 0) + item_size.width()
            if row and next_width > effective.width():
                rows.append((row, row_width, row_height))
                row = []
                row_width = 0
                row_height = 0
                next_width = item_size.width()
            row.append((item, item_size))
            row_width = next_width
            row_height = max(row_height, item_size.height())

        if row:
            rows.append((row, row_width, row_height))

        for row_items, row_width, row_height in rows:
            x = effective.x()
            extra = max(0, effective.width() - row_width)
            extra_each = extra // len(row_items) if self._justify_rows and row_items and not test_only else 0
            extra_remainder = extra % len(row_items) if self._justify_rows and row_items and not test_only else 0
            for index, (item, item_size) in enumerate(row_items):
                item_width = item_size.width() + extra_each + (1 if index < extra_remainder else 0)
                item_height = item_size.height()
                if not test_only:
                    item.setGeometry(QRect(x, y, item_width, item_height))
                x += item_width + spacing
            y += row_height + spacing

        if rows:
            y -= spacing
        return y - rect.y() + margins.bottom()