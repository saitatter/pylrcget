# ui/album_list_widget.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from PySide6.QtCore import Qt, Signal, QItemSelectionModel, QModelIndex
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QHeaderView, QMenu


@dataclass(frozen=True)
class AlbumListRow:
    album_id: int
    album: str
    artist: str | None
    track_count: int


class AlbumListWidget(QWidget):
    # Emit album_id when user wants to view/open an album
    openAlbum = Signal(int)

    def __init__(self, app_state):
        super().__init__()
        self.app_state = app_state
        self._active = True
        self._search = ""

        self.table = QTableView()
        self.model = QStandardItemModel(0, 3, self)
        self.model.setHorizontalHeaderLabels(["Album", "Artist", "Tracks"])
        self.table.setModel(self.model)

        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setObjectName("AlbumTable")
        self.table.verticalHeader().setDefaultSectionSize(24)

        # Column sizing similar to your TrackListWidget
        self.table.setColumnWidth(0, 520)
        self.table.setColumnWidth(1, 220)
        self.table.setColumnWidth(2, 70)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

        self._apply_styles()

        # Double click -> open album
        self.table.doubleClicked.connect(self._on_double_click)

        # Right-click context menu
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)

        # Sorting (optional but nice)
        self.table.setSortingEnabled(True)

    # -------------------------
    # External API
    # -------------------------

    def setActive(self, active: bool):
        self._active = active
        self.setVisible(active)
        if active:
            self.refresh()

    def setSearchValue(self, text: str):
        self._search = text or ""
        if self._active:
            self.refresh()

    def refresh(self):
        """
        Expected app_state.db and a function you implement:
            get_album_rows(db, search_query) -> iterable of dicts with keys:
              id, album, artist_name, year, track_count
        """
        from db.database import get_album_rows  # local import to avoid circulars

        db = self.app_state.db
        rows = get_album_rows(db=db, search_query=self._search)

        ui_rows: list[AlbumListRow] = []
        for r in rows:
            ui_rows.append(
                AlbumListRow(
                    album_id=int(r["album_id"]),
                    album=r["album_name"] or "",
                    artist=r.get("artist_name") or None,
                    track_count=int(r.get("track_count") or 0),
                )
            )

        self.set_rows(ui_rows)

    def set_rows(self, rows: Iterable[AlbumListRow]):
        self.model.setRowCount(0)
        for r in rows:
            items = [
                self._item_text(r.album, r.album_id),
                self._item_text(r.artist or "", r.album_id),
                self._item_text(str(r.track_count), r.album_id, align=Qt.AlignmentFlag.AlignCenter),
            ]
            self.model.appendRow(items)

        # Default sort by album name
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    def current_album_id(self) -> int | None:
        sm = self.table.selectionModel()
        if sm is None or not sm.hasSelection():
            return None
        idxs = sm.selectedRows()
        if not idxs:
            return None
        album_id = idxs[0].data(Qt.ItemDataRole.UserRole)
        try:
            return int(album_id)
        except Exception:
            return None

    def set_selected_album(self, album_id: int | None):
        if album_id is None:
            self.table.clearSelection()
            return

        row = self._row_for_album_id(album_id)
        if row < 0:
            return

        idx = self.model.index(row, 0)
        sm = self.table.selectionModel()
        if sm is None:
            return

        sm.setCurrentIndex(idx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        self.table.scrollTo(idx, QTableView.ScrollHint.PositionAtCenter)

    # -------------------------
    # UI Events
    # -------------------------

    def _on_double_click(self, index: QModelIndex):
        if not index.isValid():
            return
        album_id = self.model.index(index.row(), 0).data(Qt.ItemDataRole.UserRole)
        if album_id is None:
            return
        self.openAlbum.emit(int(album_id))

    def _on_context_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return

        album_id = self.model.index(idx.row(), 0).data(Qt.ItemDataRole.UserRole)
        if album_id is None:
            return
        album_id = int(album_id)

        menu = QMenu(self)
        act_open = menu.addAction("Open album")

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == act_open:
            self.openAlbum.emit(album_id)

    # -------------------------
    # Helpers
    # -------------------------

    def _row_for_album_id(self, album_id: int) -> int:
        for row in range(self.model.rowCount()):
            v = self.model.index(row, 0).data(Qt.ItemDataRole.UserRole)
            if v is not None and int(v) == int(album_id):
                return row
        return -1

    def _item_text(self, text: str, album_id: int, align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignVCenter):
        it = QStandardItem(text)
        it.setEditable(False)
        it.setData(int(album_id), Qt.ItemDataRole.UserRole)
        it.setTextAlignment(align)
        return it

    def _apply_styles(self):
        self.setStyleSheet("""
        QTableView#AlbumTable {
            background-color: #020617;
            alternate-background-color: #030712;
            border: none;
            color: #e5e7eb;
            gridline-color: #020617;
            selection-background-color: rgba(56, 189, 248, 0.2);
            selection-color: #e5e7eb;
        }

        QHeaderView::section {
            background-color: #020617;
            color: #9ca3af;
            padding: 4px 6px;
            border: none;
            border-bottom: 1px solid #111827;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }

        QTableView::item {
            padding: 4px 6px;
        }
        """)
