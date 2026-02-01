from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from PySide6.QtCore import Qt, Signal, QItemSelectionModel, QModelIndex
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QMenu


@dataclass(frozen=True)
class ArtistListRow:
    artist_id: int
    artist: str
    albums: int
    tracks: int


class ArtistListWidget(QWidget):
    openArtist = Signal(int)  # artist_id

    def __init__(self, app_state):
        super().__init__()
        self.app_state = app_state
        self._active = True
        self._search = ""

        self.table = QTableView()
        self.model = QStandardItemModel(0, 3, self)
        self.model.setHorizontalHeaderLabels(["Artist", "Albums", "Tracks"])
        self.table.setModel(self.model)

        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setObjectName("ArtistTable")
        self.table.verticalHeader().setDefaultSectionSize(24)

        self.table.setColumnWidth(0, 520)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 90)
        self.table.horizontalHeader().setStretchLastSection(True)

        self._apply_styles()

        self.table.doubleClicked.connect(self._on_double_click)

        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)

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
        from db.database import get_artist_rows

        rows = get_artist_rows(self.app_state.db, self._search)

        ui_rows: list[ArtistListRow] = []
        for r in rows:
            ui_rows.append(
                ArtistListRow(
                    artist_id=int(r["artist_id"]),
                    artist=r["artist_name"] or "",
                    albums=int(r.get("album_count") or 0),
                    tracks=int(r.get("track_count") or 0),
                )
            )

        self.set_rows(ui_rows)

    def set_rows(self, rows: Iterable[ArtistListRow]):
        self.model.setRowCount(0)
        for r in rows:
            items = [
                self._item_text(r.artist, r.artist_id),
                self._item_text(str(r.albums), r.artist_id, align=Qt.AlignmentFlag.AlignCenter),
                self._item_text(str(r.tracks), r.artist_id, align=Qt.AlignmentFlag.AlignCenter),
            ]
            self.model.appendRow(items)

        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    def current_artist_id(self) -> int | None:
        sm = self.table.selectionModel()
        if sm is None or not sm.hasSelection():
            return None
        idxs = sm.selectedRows()
        if not idxs:
            return None
        try:
            return int(idxs[0].data(Qt.ItemDataRole.UserRole))
        except Exception:
            return None

    # -------------------------
    # UI Events
    # -------------------------

    def _on_double_click(self, index: QModelIndex):
        if not index.isValid():
            return
        artist_id = self.model.index(index.row(), 0).data(Qt.ItemDataRole.UserRole)
        if artist_id is not None:
            self.openArtist.emit(int(artist_id))

    def _on_context_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return

        artist_id = self.model.index(idx.row(), 0).data(Qt.ItemDataRole.UserRole)
        if artist_id is None:
            return
        artist_id = int(artist_id)

        menu = QMenu(self)
        act_open = menu.addAction("Open artist")

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == act_open:
            self.openArtist.emit(artist_id)

    # -------------------------
    # Helpers
    # -------------------------

    def _item_text(self, text: str, artist_id: int, align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignVCenter):
        it = QStandardItem(text)
        it.setEditable(False)
        it.setData(int(artist_id), Qt.ItemDataRole.UserRole)
        it.setTextAlignment(align)
        return it

    def _apply_styles(self):
        self.setStyleSheet("""
        QTableView#ArtistTable {
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
