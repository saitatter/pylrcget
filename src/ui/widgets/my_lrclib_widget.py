from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QMenu, QTableView, QVBoxLayout, QWidget

from db.database import get_publish_history_rows
from ui.style_loader import load_stylesheet
from ui.widgets.empty_state_widget import EmptyStateWidget
from ui.widgets.sortable_header_view import SortableHeaderView


TRACK_ID_ROLE = Qt.ItemDataRole.UserRole
TRACK_EXISTS_ROLE = Qt.ItemDataRole.UserRole + 1


class MyLrclibWidget(QWidget):
    playTrack = Signal(int)

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.table = QTableView()
        self.table.setObjectName("MyLrclibTable")
        self.model = QStandardItemModel(0, 7, self)
        self.model.setHorizontalHeaderLabels(
            ["Status", "Type", "Title", "Artist", "Album", "Published", "LRCLIB"]
        )
        self.table.setModel(self.model)
        self.header = SortableHeaderView(
            Qt.Orientation.Horizontal,
            self.table,
            default_sort_column=5,
            default_sort_order=Qt.SortOrder.DescendingOrder,
            non_sortable_columns={0, 1, 2, 3, 4, 5, 6},
        )
        self.table.setHorizontalHeader(self.header)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.setColumnWidth(0, 90)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 260)
        self.table.setColumnWidth(3, 180)
        self.table.setColumnWidth(4, 180)
        self.table.setColumnWidth(5, 160)
        self.header.setStretchLastSection(True)

        self.empty_state = EmptyStateWidget()
        self.empty_state.configure(
            icon_name="check.svg",
            title="No published contributions yet",
            body="Publish synced or plain lyrics from the editor and they will appear here as a local contribution history.",
            action_text=None,
        )

        root.addWidget(self.table)
        root.addWidget(self.empty_state)

        self._apply_styles()
        self.refresh()

    def refresh(self) -> None:
        self.model.setRowCount(0)
        rows = get_publish_history_rows(self.app_state.db, limit=500)
        for row in rows:
            self.model.appendRow(
                [
                    self._item(str(row["publish_status"] or "Published"), row),
                    self._item(self._display_kind(row["publish_kind"]), row),
                    self._item(str(row["title"] or ""), row),
                    self._item(str(row["artist_name"] or ""), row),
                    self._item(str(row["album_name"] or ""), row),
                    self._item(str(row["published_at"] or ""), row),
                    self._item(str(row["lrclib_instance"] or ""), row),
                ]
            )

        has_rows = self.model.rowCount() > 0
        self.table.setVisible(has_rows)
        self.empty_state.setVisible(not has_rows)

    def _item(self, text: str, row) -> QStandardItem:
        item = QStandardItem(text)
        item.setEditable(False)
        item.setData(int(row["track_id"]) if row["track_id"] is not None else None, TRACK_ID_ROLE)
        item.setData(bool(row["track_exists"]), TRACK_EXISTS_ROLE)
        return item

    def _row_track_id(self, row_index: int) -> int | None:
        if row_index < 0:
            return None
        index = self.model.index(row_index, 0)
        track_id = index.data(TRACK_ID_ROLE)
        track_exists = bool(index.data(TRACK_EXISTS_ROLE))
        if track_id is None or not track_exists:
            return None
        return int(track_id)

    def _on_double_click(self, index) -> None:
        if not index.isValid():
            return
        track_id = self._row_track_id(index.row())
        if track_id is not None:
            self.playTrack.emit(track_id)

    def _on_context_menu(self, pos) -> None:
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        track_id = self._row_track_id(idx.row())
        menu = QMenu(self)
        info = menu.addAction(self.model.index(idx.row(), 2).data() or "Published lyrics")
        info.setEnabled(False)
        menu.addSeparator()
        act_play = menu.addAction("Play track")
        act_play.setEnabled(track_id is not None)
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == act_play and track_id is not None:
            self.playTrack.emit(track_id)

    @staticmethod
    def _display_kind(value: str | None) -> str:
        text = (value or "").strip().lower()
        if text == "synced":
            return "Synced"
        if text == "plain":
            return "Plain"
        return text.title() if text else "Unknown"

    def _apply_styles(self) -> None:
        self.setStyleSheet(load_stylesheet("data_table.qss", table_name="MyLrclibTable"))

