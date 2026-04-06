from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from PySide6.QtCore import Qt, Signal, QModelIndex, QItemSelectionModel
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QMenu, QStackedWidget

from ui.style_loader import load_stylesheet
from ui.widgets.album_list_widget import AlbumListWidget
from ui.widgets.sortable_header_view import SortableHeaderView


@dataclass(frozen=True)
class ArtistListRow:
    artist_ids: tuple[int, ...]
    artist: str
    albums: int
    tracks: int


class ArtistListWidget(QWidget):
    playTrack = Signal(int)
    downloadLyrics = Signal(int)
    openArtist = Signal(int)
    openAlbum = Signal(int)
    markInstrumental = Signal(list)
    unmarkInstrumental = Signal(list)
    clearFiltersRequested = Signal()
    configureFoldersRequested = Signal()

    def __init__(self, app_state):
        super().__init__()
        self.app_state = app_state
        self._active = True
        self._search = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        self.browser_page = QWidget()
        browser_layout = QVBoxLayout(self.browser_page)
        browser_layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableView()
        self.model = QStandardItemModel(0, 3, self)
        self.model.setHorizontalHeaderLabels(["Artist", "Albums", "Tracks"])
        self.table.setModel(self.model)
        self.header = SortableHeaderView(
            Qt.Orientation.Horizontal,
            self.table,
            default_sort_column=0,
            default_sort_order=Qt.SortOrder.AscendingOrder,
        )
        self.table.setHorizontalHeader(self.header)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setObjectName("ArtistTable")
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setColumnWidth(0, 520)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 90)
        self.header.setStretchLastSection(True)
        self.table.setSortingEnabled(True)
        browser_layout.addWidget(self.table)
        self.stack.addWidget(self.browser_page)

        self.album_browser = AlbumListWidget(self.app_state)
        self.album_browser.playTrack.connect(self.playTrack.emit)
        self.album_browser.downloadLyrics.connect(self.downloadLyrics.emit)
        self.album_browser.openArtist.connect(self.openArtist.emit)
        self.album_browser.openAlbum.connect(self.openAlbum.emit)
        self.album_browser.markInstrumental.connect(self.markInstrumental.emit)
        self.album_browser.unmarkInstrumental.connect(self.unmarkInstrumental.emit)
        self.album_browser.clearFiltersRequested.connect(self.clearFiltersRequested.emit)
        self.album_browser.configureFoldersRequested.connect(self.configureFoldersRequested.emit)
        self.album_browser.backRequested.connect(self._return_to_artists)
        self.stack.addWidget(self.album_browser)

        self.table.doubleClicked.connect(self._on_double_click)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)

        self._apply_styles()

    @staticmethod
    def _display_artist(value: str | None) -> str:
        text = (value or "").strip()
        if text.casefold() in {"", "artist", "unknown artist"}:
            return "N/A"
        return text

    def setActive(self, active: bool):
        self._active = active
        self.setVisible(active)
        if active:
            self.refresh()

    def setSearchValue(self, text: str):
        self._search = text or ""
        if self._active and self.stack.currentWidget() is self.browser_page:
            self.refresh()

    def refresh(self):
        from db.database import get_artist_rows

        rows = get_artist_rows(self.app_state.db, self._search)
        ui_rows: list[ArtistListRow] = []
        unknown_artist_ids: list[int] = []
        unknown_album_count = 0
        unknown_track_count = 0
        for r in rows:
            artist_id = int(r["artist_id"])
            artist_name = r["artist_name"] or ""
            display_artist = self._display_artist(artist_name)
            if display_artist == "N/A":
                unknown_artist_ids.append(artist_id)
                unknown_album_count += int(r.get("album_count") or 0)
                unknown_track_count += int(r.get("track_count") or 0)
                continue

            ui_rows.append(
                ArtistListRow(
                    artist_ids=(artist_id,),
                    artist=display_artist,
                    albums=int(r.get("album_count") or 0),
                    tracks=int(r.get("track_count") or 0),
                )
            )
        if unknown_artist_ids:
            ui_rows.append(
                ArtistListRow(
                    artist_ids=tuple(unknown_artist_ids),
                    artist="N/A",
                    albums=unknown_album_count,
                    tracks=unknown_track_count,
                )
            )

        self.set_rows(ui_rows)

    def set_rows(self, rows: Iterable[ArtistListRow]):
        self.model.setRowCount(0)
        for r in rows:
            items = [
                self._item_text(r.artist, r.artist_ids),
                self._item_text(str(r.albums), r.artist_ids, align=Qt.AlignmentFlag.AlignCenter),
                self._item_text(str(r.tracks), r.artist_ids, align=Qt.AlignmentFlag.AlignCenter),
            ]
            self.model.appendRow(items)

        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    def _show_artist_albums(self, artist_id: int | list[int] | tuple[int, ...], artist_name: str) -> None:
        artist_ids = [int(v) for v in artist_id] if isinstance(artist_id, (list, tuple)) else [int(artist_id)]
        self.album_browser.setArtistScope(artist_ids[0] if len(artist_ids) == 1 else artist_ids, self._display_artist(artist_name))
        self.stack.setCurrentWidget(self.album_browser)

    def show_artist_albums(self, artist_id: int | list[int] | tuple[int, ...], artist_name: str = "") -> None:
        self._show_artist_albums(artist_id, artist_name)

    def show_album_tracks(self, album_id: int, album_name: str = "") -> None:
        self.album_browser.show_album_tracks(int(album_id), album_name)
        self.stack.setCurrentWidget(self.album_browser)

    def _return_to_artists(self) -> None:
        self.album_browser.clearArtistScope()
        self.stack.setCurrentWidget(self.browser_page)
        if self._active:
            self.refresh()

    def _on_double_click(self, index: QModelIndex):
        if not index.isValid():
            return
        artist_id = self.model.index(index.row(), 0).data(Qt.ItemDataRole.UserRole)
        artist_name = self.model.index(index.row(), 0).data(Qt.ItemDataRole.DisplayRole) or "N/A"
        if artist_id is not None:
            if isinstance(artist_id, tuple):
                self._show_artist_albums(list(artist_id), str(artist_name))
            else:
                self._show_artist_albums(int(artist_id), str(artist_name))

    def _on_context_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return

        sm = self.table.selectionModel()
        if sm is not None and not sm.isRowSelected(idx.row(), idx.parent()):
            sm.setCurrentIndex(idx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)

        artist_id = self.model.index(idx.row(), 0).data(Qt.ItemDataRole.UserRole)
        if artist_id is None:
            return
        artist_name = self.model.index(idx.row(), 0).data(Qt.ItemDataRole.DisplayRole) or "N/A"

        menu = QMenu(self)
        info = menu.addAction(str(artist_name))
        info.setEnabled(False)
        menu.addSeparator()
        browse = menu.addAction("Browse")
        browse.setEnabled(False)
        act_open = menu.addAction("Open artist")

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == act_open:
            if isinstance(artist_id, tuple):
                self._show_artist_albums(list(artist_id), str(artist_name))
            else:
                self._show_artist_albums(int(artist_id), str(artist_name))

    def _item_text(self, text: str, artist_id: int | tuple[int, ...], align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignVCenter):
        it = QStandardItem(text)
        it.setEditable(False)
        it.setData(tuple(int(v) for v in artist_id) if isinstance(artist_id, tuple) else int(artist_id), Qt.ItemDataRole.UserRole)
        it.setTextAlignment(align)
        return it

    def _apply_styles(self):
        self.setStyleSheet(load_stylesheet("data_table.qss", table_name="ArtistTable"))
