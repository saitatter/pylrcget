from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from PySide6.QtCore import Qt, Signal, QItemSelectionModel, QModelIndex
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QHeaderView, QMenu, QHBoxLayout, QLabel, QPushButton, QStackedWidget

from ui.style_loader import load_stylesheet
from ui.widgets.sortable_header_view import SortableHeaderView
from ui.widgets.track_list_widget import TrackListWidget


@dataclass(frozen=True)
class AlbumListRow:
    album_ids: tuple[int, ...]
    album: str
    artist: str | None
    track_count: int


class AlbumListWidget(QWidget):
    playTrack = Signal(int)
    downloadLyrics = Signal(int)
    openArtist = Signal(int)
    openAlbum = Signal(int)
    markInstrumental = Signal(list)
    unmarkInstrumental = Signal(list)
    clearFiltersRequested = Signal()
    configureFoldersRequested = Signal()
    backRequested = Signal()

    def __init__(self, app_state):
        super().__init__()
        self.app_state = app_state
        self._active = True
        self._search = ""
        self._artist_id: int | None = None
        self._artist_ids: list[int] | None = None
        self._artist_name: str = ""
        self._detail_album_id: int | None = None
        self._detail_album_name: str = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.header_bar = QWidget()
        self.header_bar.setObjectName("TrackScopeBar")
        header_layout = QHBoxLayout(self.header_bar)
        header_layout.setContentsMargins(10, 6, 10, 6)
        header_layout.setSpacing(8)
        self.back_btn = QPushButton("Back")
        self.back_btn.setObjectName("TrackScopeClearButton")
        self.header_label = QLabel("")
        self.header_label.setObjectName("TrackScopeLabel")
        header_layout.addWidget(self.back_btn)
        header_layout.addWidget(self.header_label, 1)
        root.addWidget(self.header_bar)
        self.header_bar.hide()

        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        self.browser_page = QWidget()
        browser_layout = QVBoxLayout(self.browser_page)
        browser_layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableView()
        self.model = QStandardItemModel(0, 3, self)
        self.model.setHorizontalHeaderLabels(["Album", "Artist", "Tracks"])
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
        self.table.setObjectName("AlbumTable")
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setColumnWidth(0, 520)
        self.table.setColumnWidth(1, 220)
        self.table.setColumnWidth(2, 70)
        self.header.setStretchLastSection(True)
        self.header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSortingEnabled(True)
        browser_layout.addWidget(self.table)
        self.stack.addWidget(self.browser_page)

        self.track_list = TrackListWidget(self.app_state)
        self.track_list.setScopeBannerEnabled(False)
        self.track_list.playTrack.connect(self.playTrack.emit)
        self.track_list.downloadLyrics.connect(self.downloadLyrics.emit)
        self.track_list.openArtist.connect(self.openArtist.emit)
        self.track_list.openAlbum.connect(self.openAlbum.emit)
        self.track_list.markInstrumental.connect(self.markInstrumental.emit)
        self.track_list.unmarkInstrumental.connect(self.unmarkInstrumental.emit)
        self.track_list.clearFiltersRequested.connect(self.clearFiltersRequested.emit)
        self.track_list.configureFoldersRequested.connect(self.configureFoldersRequested.emit)
        self.stack.addWidget(self.track_list)

        self.table.doubleClicked.connect(self._on_double_click)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.back_btn.clicked.connect(self._go_back)

        self._apply_styles()

    @staticmethod
    def _display_album(value: str | None) -> str:
        text = (value or "").strip()
        if text.casefold() in {"", "album", "unknown album"}:
            return "N/A"
        return text

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

    def setArtistScope(self, artist_id: int | list[int] | tuple[int, ...] | None, artist_name: str = "") -> None:
        if isinstance(artist_id, (list, tuple)):
            values = [int(v) for v in artist_id]
            self._artist_ids = values or None
            self._artist_id = values[0] if len(values) == 1 else None
        else:
            self._artist_id = int(artist_id) if artist_id is not None else None
            self._artist_ids = None
        self._artist_name = artist_name or ""
        self._detail_album_id = None
        self._detail_album_name = ""
        self.stack.setCurrentWidget(self.browser_page)
        self._update_header()
        if self._active:
            self.refresh()

    def clearArtistScope(self) -> None:
        self.setArtistScope(None, "")

    def refresh(self):
        from db.database import get_album_rows

        rows = get_album_rows(
            db=self.app_state.db,
            search_query=self._search,
            artist_id=self._artist_id,
            artist_ids=self._artist_ids,
        )
        ui_rows: list[AlbumListRow] = []
        unknown_album_ids: list[int] = []
        unknown_track_count = 0
        unknown_artist_names: set[str] = set()
        for r in rows:
            album_id = int(r["album_id"])
            album_name = r["album_name"] or ""
            artist_name = r.get("artist_name") or None
            display_album = self._display_album(album_name)
            display_artist = self._display_artist(artist_name)

            if display_album == "N/A":
                unknown_album_ids.append(album_id)
                unknown_track_count += int(r.get("track_count") or 0)
                if display_artist != "N/A":
                    unknown_artist_names.add(display_artist)
                continue

            ui_rows.append(
                AlbumListRow(
                    album_ids=(album_id,),
                    album=display_album,
                    artist=display_artist,
                    track_count=int(r.get("track_count") or 0),
                )
            )
        if unknown_album_ids:
            bucket_artist = "N/A" if len(unknown_artist_names) != 1 else next(iter(unknown_artist_names))
            ui_rows.append(
                AlbumListRow(
                    album_ids=tuple(unknown_album_ids),
                    album="N/A",
                    artist=bucket_artist,
                    track_count=unknown_track_count,
                )
            )
        self.set_rows(ui_rows)
        self._update_header()

    def set_rows(self, rows: Iterable[AlbumListRow]):
        self.model.setRowCount(0)
        for r in rows:
            items = [
                self._item_text(r.album, r.album_ids),
                self._item_text(self._display_artist(r.artist), r.album_ids),
                self._item_text(str(r.track_count), r.album_ids, align=Qt.AlignmentFlag.AlignCenter),
            ]
            self.model.appendRow(items)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    def show_album_tracks(self, album_id: int | list[int] | tuple[int, ...], album_name: str = "") -> None:
        album_ids = [int(v) for v in album_id] if isinstance(album_id, (list, tuple)) else [int(album_id)]
        self._detail_album_id = album_ids[0] if len(album_ids) == 1 else -1
        self._detail_album_name = self._display_album(album_name)
        self.track_list.setArtistFilter(None)
        self.track_list.setAlbumFilterLabel(self._detail_album_name)
        self.track_list.setAlbumFilter(album_ids if len(album_ids) > 1 else album_ids[0])
        self.stack.setCurrentWidget(self.track_list)
        self._update_header()

    def _go_back(self) -> None:
        if self.stack.currentWidget() is self.track_list:
            self.track_list.setAlbumFilter(None)
            self.track_list.setAlbumFilterLabel("")
            self._detail_album_id = None
            self._detail_album_name = ""
            self.stack.setCurrentWidget(self.browser_page)
            self._update_header()
            if self._active:
                self.refresh()
            return
        if self._artist_id is not None or self._artist_ids:
            self.backRequested.emit()

    def _update_header(self) -> None:
        if self.stack.currentWidget() is self.track_list:
            self.header_bar.show()
            self.header_label.setText(f"Album: {self._detail_album_name or 'N/A'}")
            return
        if self._artist_id is not None or self._artist_ids:
            self.header_bar.show()
            self.header_label.setText(f"Artist: {self._display_artist(self._artist_name)}")
            return
        self.header_bar.hide()
        self.header_label.setText("")

    def _on_double_click(self, index: QModelIndex):
        if not index.isValid():
            return
        album_id = self.model.index(index.row(), 0).data(Qt.ItemDataRole.UserRole)
        album_name = self.model.index(index.row(), 0).data(Qt.ItemDataRole.DisplayRole) or ""
        if album_id is None:
            return
        if isinstance(album_id, tuple):
            self.show_album_tracks(list(album_id), str(album_name))
        else:
            self.show_album_tracks(int(album_id), str(album_name))

    def _on_context_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        sm = self.table.selectionModel()
        if sm is not None and not sm.isRowSelected(idx.row(), idx.parent()):
            sm.setCurrentIndex(idx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)

        album_id = self.model.index(idx.row(), 0).data(Qt.ItemDataRole.UserRole)
        if album_id is None:
            return
        album_name = self.model.index(idx.row(), 0).data(Qt.ItemDataRole.DisplayRole) or "N/A"

        menu = QMenu(self)
        info = menu.addAction(str(album_name))
        info.setEnabled(False)
        menu.addSeparator()
        browse = menu.addAction("Browse")
        browse.setEnabled(False)
        act_open = menu.addAction("Open album")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == act_open:
            if isinstance(album_id, tuple):
                self.show_album_tracks(list(album_id), str(album_name))
            else:
                self.show_album_tracks(int(album_id), str(album_name))

    def _item_text(self, text: str, album_id: int | tuple[int, ...], align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignVCenter):
        it = QStandardItem(text)
        it.setEditable(False)
        it.setData(tuple(int(v) for v in album_id) if isinstance(album_id, tuple) else int(album_id), Qt.ItemDataRole.UserRole)
        it.setTextAlignment(align)
        return it

    def _apply_styles(self):
        self.setStyleSheet(load_stylesheet("data_table.qss", table_name="AlbumTable"))
