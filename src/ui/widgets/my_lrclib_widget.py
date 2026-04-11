from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QMenu, QTableView, QTabWidget, QVBoxLayout, QWidget

from db.database import get_download_history_rows, get_publish_history_rows
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

        self.tabs = QTabWidget()
        self.tabs.setObjectName("MyLrclibTabs")
        root.addWidget(self.tabs)

        self.publish_table, self.publish_model, self.publish_empty = self._build_table_page(
            table_name="MyLrclibTable",
            headers=["Status", "Type", "Title", "Artist", "Album", "Published", "LRCLIB"],
            column_widths=[90, 80, 260, 180, 180, 160],
            empty_icon="check.svg",
            empty_title="No published contributions yet",
            empty_body="Publish synced or plain lyrics from the editor and they will appear here as a local contribution history.",
            default_sort_column=5,
        )
        self.download_table, self.download_model, self.download_empty = self._build_table_page(
            table_name="DownloadHistoryTable",
            headers=["Result", "Mode", "Title", "Artist", "Album", "Downloaded", "Details"],
            column_widths=[90, 120, 260, 180, 180, 160],
            empty_icon="download.svg",
            empty_title="No lyrics downloads yet",
            empty_body="Bulk or single-track lyrics downloads will appear here as a persistent local history.",
            default_sort_column=5,
        )

        self.tabs.addTab(self._wrap_page(self.publish_table, self.publish_empty), "Published")
        self.tabs.addTab(self._wrap_page(self.download_table, self.download_empty), "Downloads")

        self._apply_styles()
        self.refresh()

    def _build_table_page(
        self,
        *,
        table_name: str,
        headers: list[str],
        column_widths: list[int],
        empty_icon: str,
        empty_title: str,
        empty_body: str,
        default_sort_column: int,
    ) -> tuple[QTableView, QStandardItemModel, EmptyStateWidget]:
        table = QTableView()
        table.setObjectName(table_name)
        model = QStandardItemModel(0, len(headers), self)
        model.setHorizontalHeaderLabels(headers)
        table.setModel(model)
        header = SortableHeaderView(
            Qt.Orientation.Horizontal,
            table,
            default_sort_column=default_sort_column,
            default_sort_order=Qt.SortOrder.DescendingOrder,
            non_sortable_columns=set(range(len(headers))),
        )
        table.setHorizontalHeader(header)
        table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(
            lambda pos, t=table, m=model: self._on_context_menu(t, m, pos)
        )
        table.doubleClicked.connect(lambda index, m=model: self._on_double_click(m, index))
        for idx, width in enumerate(column_widths):
            table.setColumnWidth(idx, width)
        header.setStretchLastSection(True)

        empty_state = EmptyStateWidget()
        empty_state.configure(
            icon_name=empty_icon,
            title=empty_title,
            body=empty_body,
            action_text=None,
        )
        return table, model, empty_state

    @staticmethod
    def _wrap_page(table: QTableView, empty_state: EmptyStateWidget) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        root.addWidget(table)
        root.addWidget(empty_state)
        return page

    def refresh(self) -> None:
        self.refresh_published()
        self.refresh_downloads()

    def refresh_published(self) -> None:
        self.publish_model.setRowCount(0)
        rows = get_publish_history_rows(self.app_state.db, limit=500)
        for row in rows:
            self.publish_model.appendRow(
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
        self._apply_page_visibility(self.publish_table, self.publish_empty, self.publish_model.rowCount() > 0)

    def refresh_downloads(self) -> None:
        self.download_model.setRowCount(0)
        rows = get_download_history_rows(self.app_state.db, limit=500)
        for row in rows:
            self.download_model.appendRow(
                [
                    self._item(self._display_download_status(row["download_status"]), row),
                    self._item(self._display_download_mode(row["download_mode"]), row),
                    self._item(str(row["title"] or ""), row),
                    self._item(str(row["artist_name"] or ""), row),
                    self._item(str(row["album_name"] or ""), row),
                    self._item(str(row["downloaded_at"] or ""), row),
                    self._item(str(row["message"] or ""), row),
                ]
            )
        self._apply_page_visibility(self.download_table, self.download_empty, self.download_model.rowCount() > 0)

    @staticmethod
    def _apply_page_visibility(table: QTableView, empty_state: EmptyStateWidget, has_rows: bool) -> None:
        table.setVisible(has_rows)
        empty_state.setVisible(not has_rows)

    def _item(self, text: str, row) -> QStandardItem:
        item = QStandardItem(text)
        item.setEditable(False)
        item.setData(int(row["track_id"]) if row["track_id"] is not None else None, TRACK_ID_ROLE)
        item.setData(bool(row["track_exists"]), TRACK_EXISTS_ROLE)
        return item

    @staticmethod
    def _row_track_id(model: QStandardItemModel, row_index: int) -> int | None:
        if row_index < 0:
            return None
        index = model.index(row_index, 0)
        track_id = index.data(TRACK_ID_ROLE)
        track_exists = bool(index.data(TRACK_EXISTS_ROLE))
        if track_id is None or not track_exists:
            return None
        return int(track_id)

    def _on_double_click(self, model: QStandardItemModel, index) -> None:
        if not index.isValid():
            return
        track_id = self._row_track_id(model, index.row())
        if track_id is not None:
            self.playTrack.emit(track_id)

    def _on_context_menu(self, table: QTableView, model: QStandardItemModel, pos) -> None:
        idx = table.indexAt(pos)
        if not idx.isValid():
            return
        track_id = self._row_track_id(model, idx.row())
        menu = QMenu(self)
        info = menu.addAction(model.index(idx.row(), 2).data() or "Lyrics history")
        info.setEnabled(False)
        menu.addSeparator()
        act_play = menu.addAction("Play track")
        act_play.setEnabled(track_id is not None)
        chosen = menu.exec(table.viewport().mapToGlobal(pos))
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

    @staticmethod
    def _display_download_mode(value: str | None) -> str:
        mapping = {
            "prefer_synced": "Prefer synced",
            "synced_only": "Synced only",
            "plain_only": "Plain only",
        }
        return mapping.get((value or "").strip(), (value or "").strip().title() or "Unknown")

    @staticmethod
    def _display_download_status(value: str | None) -> str:
        mapping = {
            "synced": "Synced",
            "plain": "Plain",
            "not_found": "Not Found",
            "instrumental": "Instrumental",
            "error": "Error",
        }
        return mapping.get((value or "").strip(), (value or "").strip().title() or "Unknown")

    def _apply_styles(self) -> None:
        qss = load_stylesheet("data_table.qss", table_name="MyLrclibTable")
        qss += "\n" + load_stylesheet("data_table.qss", table_name="DownloadHistoryTable")
        self.setStyleSheet(qss)
