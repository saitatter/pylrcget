from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHeaderView, QMenu


class SortableHeaderView(QHeaderView):
    def __init__(
        self,
        orientation: Qt.Orientation,
        parent=None,
        *,
        default_sort_column: int = 0,
        default_sort_order: Qt.SortOrder = Qt.SortOrder.AscendingOrder,
        non_sortable_columns: set[int] | None = None,
    ):
        super().__init__(orientation, parent)
        self._default_sort_column = default_sort_column
        self._default_sort_order = default_sort_order
        self._non_sortable_columns = set(non_sortable_columns or set())

        self.setSectionsClickable(True)
        self.setSortIndicatorShown(True)
        self.setHighlightSections(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._open_context_menu)
        self.sectionClicked.connect(self._handle_section_clicked)

    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int) -> None:
        super().paintSection(painter, rect, logical_index)

        if logical_index != self.sortIndicatorSection():
            return
        if logical_index in self._non_sortable_columns:
            return

        arrow = "\u25B2" if self.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder else "\u25BC"
        arrow_rect = rect.adjusted(0, 0, -8, 0)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setPen(QColor("#38bdf8"))
        painter.drawText(arrow_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, arrow)

        underline_y = rect.bottom() - 1
        painter.fillRect(QRect(rect.left() + 6, underline_y, max(0, rect.width() - 12), 2), QColor("#38bdf8"))
        painter.restore()

    def reset_to_default_sort(self) -> None:
        self._sort_column(self._default_sort_column, self._default_sort_order)

    def _handle_section_clicked(self, logical_index: int) -> None:
        if logical_index in self._non_sortable_columns:
            self._sort_column(self.sortIndicatorSection(), self.sortIndicatorOrder())

    def _open_context_menu(self, pos: QPoint) -> None:
        column = self.logicalIndexAt(pos)
        if column < 0:
            return

        menu = QMenu(self)
        act_reset = menu.addAction("Reset to default sort")

        act_asc = None
        act_desc = None
        if column not in self._non_sortable_columns:
            act_asc = menu.addAction("Sort ascending")
            act_desc = menu.addAction("Sort descending")

        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        if chosen == act_asc:
            self._sort_column(column, Qt.SortOrder.AscendingOrder)
        elif chosen == act_desc:
            self._sort_column(column, Qt.SortOrder.DescendingOrder)
        elif chosen == act_reset:
            self.reset_to_default_sort()

    def _sort_column(self, column: int, order: Qt.SortOrder) -> None:
        parent = self.parent()
        if parent is None or not hasattr(parent, "sortByColumn"):
            return
        if column < 0:
            column = self._default_sort_column
        parent.sortByColumn(column, order)
        self.setSortIndicator(column, order)
        self.viewport().update()
