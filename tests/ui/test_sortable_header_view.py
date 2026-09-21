from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableView

from tests.test_support import qt_app
from ui.widgets.sortable_header_view import SortableHeaderView


def test_sortable_header_uses_only_the_custom_sort_indicator() -> None:
    app = qt_app()
    table = QTableView()
    header = SortableHeaderView(
        Qt.Orientation.Horizontal,
        table,
        default_sort_column=0,
        default_sort_order=Qt.SortOrder.AscendingOrder,
    )

    try:
        assert not header.isSortIndicatorShown()
    finally:
        header.deleteLater()
        table.deleteLater()
        app.processEvents()
