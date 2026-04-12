from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt, Signal, QModelIndex, QItemSelectionModel
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QMenu, QStackedWidget

from db.database import get_directories
from ui.style_loader import load_stylesheet
from ui.library_routes import LibraryRoute, artists_detail
from ui.widgets.album_list_widget import AlbumListWidget
from ui.widgets.empty_state_widget import EmptyStateWidget
from ui.widgets.library_rows import ArtistListRow
from ui.widgets.library_table_utils import (
    build_text_item,
    display_artist_name,
    find_display_row,
    normalize_id_bucket,
    should_load_more,
)
from ui.widgets.sortable_header_view import SortableHeaderView


class ArtistListWidget(QWidget):
    playTrack = Signal(int)
    refreshTrack = Signal(int)
    downloadLyrics = Signal(int)
    exportLyricsFiles = Signal(int)
    bulkDownloadRequested = Signal(list, str)
    openArtist = Signal(int)
    openAlbum = Signal(int)
    markInstrumental = Signal(list)
    unmarkInstrumental = Signal(list)
    clearFiltersRequested = Signal()
    clearSearchRequested = Signal()
    refreshLibraryRequested = Signal()
    configureFoldersRequested = Signal()
    navigateRequested = Signal(object)

    def __init__(self, app_state):
        super().__init__()
        self.app_state = app_state
        self._active = True
        self._search = ""
        self._page_size = 200
        self._sort_column = 0
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._has_more_rows = False
        self._loading_more = False
        self._loaded_db_rows = 0
        self._unknown_artist_ids: list[int] = []
        self._unknown_album_count = 0
        self._unknown_track_count = 0
        self._ui_scale = 1.0

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
        self.table.setSortingEnabled(False)
        self.header.setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.header.sortIndicatorChanged.connect(self._on_sort_changed)
        self.table.verticalScrollBar().valueChanged.connect(self._maybe_load_more)
        browser_layout.addWidget(self.table)

        self.empty_state = EmptyStateWidget()
        self.empty_state.actionTriggered.connect(self._on_empty_state_action)
        browser_layout.addWidget(self.empty_state)
        self.empty_state.hide()
        self.stack.addWidget(self.browser_page)

        self.album_browser = AlbumListWidget(self.app_state)
        self.album_browser.setRouteTab("artists")
        self.album_browser.playTrack.connect(self.playTrack.emit)
        self.album_browser.refreshTrack.connect(self.refreshTrack.emit)
        self.album_browser.downloadLyrics.connect(self.downloadLyrics.emit)
        self.album_browser.exportLyricsFiles.connect(self.exportLyricsFiles.emit)
        self.album_browser.bulkDownloadRequested.connect(self.bulkDownloadRequested.emit)
        self.album_browser.openArtist.connect(self.openArtist.emit)
        self.album_browser.openAlbum.connect(self.openAlbum.emit)
        self.album_browser.navigateRequested.connect(self.navigateRequested.emit)
        self.album_browser.markInstrumental.connect(self.markInstrumental.emit)
        self.album_browser.unmarkInstrumental.connect(self.unmarkInstrumental.emit)
        self.album_browser.clearFiltersRequested.connect(self.clearFiltersRequested.emit)
        self.album_browser.configureFoldersRequested.connect(self.configureFoldersRequested.emit)
        self.stack.addWidget(self.album_browser)

        self.table.doubleClicked.connect(self._on_double_click)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)

        self._apply_styles()
        self._empty_action = ""

    def set_ui_scale(self, scale: float) -> None:
        self._ui_scale = max(0.85, min(1.5, float(scale or 1.0)))
        self.table.verticalHeader().setDefaultSectionSize(int(round(30 * self._ui_scale)))
        self.album_browser.set_ui_scale(self._ui_scale)

    def setActive(self, active: bool):
        self._active = active
        self.setVisible(active)
        if active:
            self.refresh()

    def setSearchValue(self, text: str):
        self._search = text or ""
        if self._active and self.stack.currentWidget() is self.browser_page:
            self.refresh()

    def apply_route(self, route: LibraryRoute) -> None:
        if route.tab != "artists":
            return

        if route.mode == "root":
            self._return_to_artists()
            return
        if route.mode == "artist":
            self.show_artist_albums(list(route.artist_ids) if len(route.artist_ids) > 1 else (route.artist_ids[0] if route.artist_ids else None), route.artist_label)
            return
        if route.mode == "artist_album":
            self.show_artist_albums(list(route.artist_ids) if len(route.artist_ids) > 1 else (route.artist_ids[0] if route.artist_ids else None), route.artist_label)
            self.show_album_tracks(list(route.album_ids) if len(route.album_ids) > 1 else (route.album_ids[0] if route.album_ids else None), route.album_label)
            return

    def refresh(self):
        self._load_rows(reset=True)

    def set_download_state(self, track_id: int, state: str) -> None:
        self.album_browser.set_download_state(track_id, state)

    def get_download_state(self, track_id: int) -> str:
        return self.album_browser.get_download_state(track_id)

    def _load_rows(self, *, reset: bool) -> None:
        from db.database import get_artist_rows

        directories = get_directories(self.app_state.db)
        if not directories:
            self.model.setRowCount(0)
            self._has_more_rows = False
            self._show_empty_state(
                icon_name="folder-open.svg",
                title="No music folders yet",
                body="Add one or more folders to build your library and start browsing artists.",
                action_text="Open Settings",
                action_key="configure-folders",
            )
            return

        rows = get_artist_rows(
            self.app_state.db,
            self._search,
            limit=self._page_size + 1,
            offset=0 if reset else self._loaded_db_rows,
            sort_column=self._sort_column,
            sort_order="desc" if self._sort_order == Qt.SortOrder.DescendingOrder else "asc",
        )
        self._has_more_rows = len(rows) > self._page_size
        visible_rows = rows[: self._page_size]
        ui_rows: list[ArtistListRow] = []
        if reset:
            self.model.setRowCount(0)
            self._loaded_db_rows = 0
            self._unknown_artist_ids = []
            self._unknown_album_count = 0
            self._unknown_track_count = 0
        self._loaded_db_rows += len(visible_rows)
        for r in visible_rows:
            artist_id = int(r["artist_id"])
            artist_name = r["artist_name"] or ""
            display_artist = display_artist_name(artist_name)
            if display_artist == "N/A":
                self._unknown_artist_ids.append(artist_id)
                self._unknown_album_count += int(r.get("album_count") or 0)
                self._unknown_track_count += int(r.get("track_count") or 0)
                continue

            ui_rows.append(
                ArtistListRow(
                    artist_ids=(artist_id,),
                    artist=display_artist,
                    albums=int(r.get("album_count") or 0),
                    tracks=int(r.get("track_count") or 0),
                )
            )
        self._append_rows(ui_rows, reset=reset)
        self._sync_unknown_bucket()
        self._loading_more = False
        if self.model.rowCount():
            self._show_table()
        elif self._search.strip():
            self._show_empty_state(
                icon_name="search-x.svg",
                title="No artists match your search",
                body="Try a different search term or clear the current search to show more artists.",
                action_text="Clear Search",
                action_key="clear-search",
            )
        else:
            self._show_empty_state(
                icon_name="audio-lines.svg",
                title="No artists found",
                body="Try refreshing the library or reviewing your scan exclusions.",
                action_text="Refresh Library",
                action_key="refresh-library",
            )

    def set_rows(self, rows: Iterable[ArtistListRow]):
        self.model.setRowCount(0)
        for r in rows:
            items = [
                build_text_item(r.artist, r.artist_ids),
                build_text_item(str(r.albums), r.artist_ids, align=Qt.AlignmentFlag.AlignCenter),
                build_text_item(str(r.tracks), r.artist_ids, align=Qt.AlignmentFlag.AlignCenter),
            ]
            self.model.appendRow(items)

        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    def _append_rows(self, rows: Iterable[ArtistListRow], *, reset: bool = False):
        if reset:
            self.model.setRowCount(0)
        for r in rows:
            items = [
                build_text_item(r.artist, r.artist_ids),
                build_text_item(str(r.albums), r.artist_ids, align=Qt.AlignmentFlag.AlignCenter),
                build_text_item(str(r.tracks), r.artist_ids, align=Qt.AlignmentFlag.AlignCenter),
            ]
            self.model.appendRow(items)

    def _show_artist_albums(self, artist_id: int | list[int] | tuple[int, ...], artist_name: str) -> None:
        artist_ids = [int(v) for v in artist_id] if isinstance(artist_id, (list, tuple)) else [int(artist_id)]
        self.album_browser.setArtistScope(artist_ids[0] if len(artist_ids) == 1 else artist_ids, display_artist_name(artist_name))
        self.stack.setCurrentWidget(self.album_browser)

    def show_artist_albums(self, artist_id: int | list[int] | tuple[int, ...], artist_name: str = "") -> None:
        self._show_artist_albums(artist_id, artist_name)

    def show_album_tracks(self, album_id: int | list[int] | tuple[int, ...], album_name: str = "") -> None:
        self.album_browser.show_album_tracks(album_id, album_name)
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
        artist_ids = normalize_id_bucket(artist_id)
        if artist_ids:
            self.navigateRequested.emit(artists_detail(artist_ids, label=str(artist_name)))

    def _on_context_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return

        sm = self.table.selectionModel()
        if sm is not None and not sm.isRowSelected(idx.row(), idx.parent()):
            sm.setCurrentIndex(idx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)

        artist_id = self.model.index(idx.row(), 0).data(Qt.ItemDataRole.UserRole)
        artist_ids = normalize_id_bucket(artist_id)
        if not artist_ids:
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
            self.navigateRequested.emit(artists_detail(artist_ids, label=str(artist_name)))

    def _apply_styles(self):
        self.setStyleSheet(load_stylesheet("data_table.qss", table_name="ArtistTable"))

    def _show_table(self) -> None:
        self.table.show()
        self.empty_state.hide()

    def _show_empty_state(self, *, icon_name: str, title: str, body: str, action_text: str, action_key: str) -> None:
        self._empty_action = action_key
        self.empty_state.configure(
            icon_name=icon_name,
            title=title,
            body=body,
            action_text=action_text,
        )
        self.table.hide()
        self.empty_state.show()

    def _on_empty_state_action(self) -> None:
        if self._empty_action == "configure-folders":
            self.configureFoldersRequested.emit()
        elif self._empty_action == "refresh-library":
            self.refreshLibraryRequested.emit()
        elif self._empty_action == "clear-search":
            self.clearSearchRequested.emit()

    def _find_unknown_row(self) -> int:
        return find_display_row(self.model, "N/A")

    def _sync_unknown_bucket(self) -> None:
        if not self._unknown_artist_ids:
            row = self._find_unknown_row()
            if row >= 0:
                self.model.removeRow(row)
            return

        row = self._find_unknown_row()
        if row < 0:
            self.model.appendRow(
                [
                    build_text_item("N/A", tuple(self._unknown_artist_ids)),
                    build_text_item(str(self._unknown_album_count), tuple(self._unknown_artist_ids), align=Qt.AlignmentFlag.AlignCenter),
                    build_text_item(str(self._unknown_track_count), tuple(self._unknown_artist_ids), align=Qt.AlignmentFlag.AlignCenter),
                ]
            )
            return

        self.model.item(row, 0).setData(tuple(self._unknown_artist_ids), Qt.ItemDataRole.UserRole)
        self.model.item(row, 1).setData(tuple(self._unknown_artist_ids), Qt.ItemDataRole.UserRole)
        self.model.item(row, 2).setData(tuple(self._unknown_artist_ids), Qt.ItemDataRole.UserRole)
        self.model.item(row, 1).setText(str(self._unknown_album_count))
        self.model.item(row, 2).setText(str(self._unknown_track_count))

    def _on_sort_changed(self, column: int, order: Qt.SortOrder) -> None:
        self._sort_column = int(column)
        self._sort_order = order
        if self._active and self.stack.currentWidget() is self.browser_page:
            self.refresh()

    def _maybe_load_more(self, value: int) -> None:
        scroll = self.table.verticalScrollBar()
        if not should_load_more(
            has_more_rows=self._has_more_rows,
            loading_more=self._loading_more,
            is_browser_visible=self.stack.currentWidget() is self.browser_page and not self.table.isHidden(),
            value=value,
            maximum=scroll.maximum(),
        ):
            return
        self._loading_more = True
        self._load_rows(reset=False)
