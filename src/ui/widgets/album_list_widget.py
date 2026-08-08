from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt, Signal, QItemSelectionModel, QModelIndex
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QHeaderView, QMenu, QHBoxLayout, QLabel, QStackedWidget

from db.database import get_directories
from ui.style_loader import load_stylesheet
from ui.library_routes import LibraryRoute, album_artists_album, albums_detail, artists_album, artists_detail
from ui.widgets.empty_state_widget import EmptyStateWidget
from ui.widgets.library_rows import AlbumListRow
from ui.widgets.library_table_utils import (
    build_text_item,
    display_album_name,
    display_artist_name,
    find_display_row,
    normalize_id_bucket,
    should_load_more,
)
from ui.widgets.sortable_header_view import SortableHeaderView
from ui.widgets.track_list_widget import TrackListWidget


class AlbumListWidget(QWidget):
    previewTrack = Signal(int)
    playTrack = Signal(int)
    refreshTrack = Signal(int)
    bulkRefreshRequested = Signal(list)
    downloadLyrics = Signal(int)
    exportLyricsFiles = Signal(int)
    importLyricsFile = Signal(int, str)
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
        self._artist_id: int | None = None
        self._artist_ids: list[int] | None = None
        self._artist_name: str = ""
        self._album_artist_name: str | None = None  # album_artists tab scope
        self._detail_album_id: int | None = None
        self._detail_album_name: str = ""
        self._route_tab = "albums"
        self._page_size = 200
        self._sort_column = 0
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._has_more_rows = False
        self._loading_more = False
        self._loaded_db_rows = 0
        self._unknown_album_ids: list[int] = []
        self._unknown_track_count = 0
        self._unknown_artist_names: set[str] = set()
        self._ui_scale = 1.0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.header_bar = QWidget()
        self.header_bar.setObjectName("TrackScopeBar")
        header_layout = QHBoxLayout(self.header_bar)
        header_layout.setContentsMargins(10, 6, 10, 6)
        header_layout.setSpacing(8)
        self.header_label = QLabel("")
        self.header_label.setObjectName("TrackScopeLabel")
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
        self.header.setStretchLastSection(False)
        self.header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
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

        self.track_list = TrackListWidget(self.app_state)
        self.track_list.setScopeBannerEnabled(False)
        self.track_list.playTrack.connect(self.playTrack.emit)
        self.track_list.previewTrack.connect(self.previewTrack.emit)
        self.track_list.refreshTrack.connect(self.refreshTrack.emit)
        self.track_list.bulkRefreshRequested.connect(self.bulkRefreshRequested.emit)
        self.track_list.downloadLyrics.connect(self.downloadLyrics.emit)
        self.track_list.exportLyricsFiles.connect(self.exportLyricsFiles.emit)
        self.track_list.importLyricsFile.connect(self.importLyricsFile.emit)
        self.track_list.bulkDownloadRequested.connect(self.bulkDownloadRequested.emit)
        self.track_list.openArtist.connect(self.openArtist.emit)
        self.track_list.openAlbum.connect(self.openAlbum.emit)
        self.track_list.navigateRequested.connect(self._handle_track_route)
        self.track_list.markInstrumental.connect(self.markInstrumental.emit)
        self.track_list.unmarkInstrumental.connect(self.unmarkInstrumental.emit)
        self.track_list.clearFiltersRequested.connect(self.clearFiltersRequested.emit)
        self.track_list.configureFoldersRequested.connect(self.configureFoldersRequested.emit)
        self.stack.addWidget(self.track_list)

        self.table.doubleClicked.connect(self._on_double_click)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)

        self._apply_styles()
        self._empty_action = ""

    def set_ui_scale(self, scale: float) -> None:
        self._ui_scale = max(0.85, min(1.5, float(scale or 1.0)))
        self.table.verticalHeader().setDefaultSectionSize(int(round(30 * self._ui_scale)))
        self.track_list.set_ui_scale(self._ui_scale)

    def apply_current_palette(self) -> None:
        self.table.viewport().update()
        self.table.update()
        self.track_list.apply_current_palette()

    def setActive(self, active: bool):
        self._active = active
        self.setVisible(active)
        if active:
            self.refresh()

    def setSearchValue(self, text: str):
        self._search = text or ""
        if self._active and self.stack.currentWidget() is self.browser_page:
            self.refresh()

    def setRouteTab(self, tab: str) -> None:
        self._route_tab = tab or "albums"

    def apply_route(self, route: LibraryRoute) -> None:
        if route.tab != self._route_tab:
            return

        if route.mode == "root":
            self.clearArtistScope()
            return
        if route.mode == "artist":
            self.setArtistScope(list(route.artist_ids) if len(route.artist_ids) > 1 else (route.artist_ids[0] if route.artist_ids else None), route.artist_label)
            return
        if route.mode == "album":
            self.clearArtistScope()
            self.show_album_tracks(list(route.album_ids) if len(route.album_ids) > 1 else (route.album_ids[0] if route.album_ids else None), route.album_label)
            return
        if route.mode == "artist_album":
            self.setArtistScope(list(route.artist_ids) if len(route.artist_ids) > 1 else (route.artist_ids[0] if route.artist_ids else None), route.artist_label)
            self.show_album_tracks(list(route.album_ids) if len(route.album_ids) > 1 else (route.album_ids[0] if route.album_ids else None), route.album_label)
            return

    def setArtistScope(self, artist_id: int | list[int] | tuple[int, ...] | None, artist_name: str = "") -> None:
        if isinstance(artist_id, (list, tuple)):
            values = [int(v) for v in artist_id]
            self._artist_ids = values or None
            self._artist_id = values[0] if len(values) == 1 else None
        else:
            self._artist_id = int(artist_id) if artist_id is not None else None
            self._artist_ids = None
        self._artist_name = artist_name or ""
        self._album_artist_name = None
        self._detail_album_id = None
        self._detail_album_name = ""
        self.stack.setCurrentWidget(self.browser_page)
        self._update_header()
        if self._active:
            self.refresh()

    def clearArtistScope(self) -> None:
        self.setArtistScope(None, "")

    def setAlbumArtistScope(self, album_artist_name: str) -> None:
        """Scope albums by album_artist_name text (used by the Album Artists tab)."""
        self._album_artist_name = album_artist_name or None
        self._artist_id = None
        self._artist_ids = None
        self._artist_name = album_artist_name or ""
        self._detail_album_id = None
        self._detail_album_name = ""
        self.stack.setCurrentWidget(self.browser_page)
        self._update_header()
        if self._active:
            self.refresh()

    def set_download_state(self, track_id: int, state: str) -> None:
        self.track_list.set_download_state(track_id, state)

    def set_dirty_lyrics_state(self, track_id: int, has_dirty_lyrics: bool) -> None:
        self.track_list.set_dirty_lyrics_state(track_id, has_dirty_lyrics)

    def update_track_lyrics_state(self, track_id: int, lyrics_state) -> None:
        self.track_list.update_track_lyrics_state(track_id, lyrics_state)

    def get_download_state(self, track_id: int) -> str:
        return self.track_list.get_download_state(track_id)

    def refresh(self):
        self._load_rows(reset=True)

    def _load_rows(self, *, reset: bool) -> None:
        from db.database import get_album_rows, get_album_rows_by_album_artist

        directories = get_directories(self.app_state.db)
        if not directories:
            self.model.setRowCount(0)
            self._has_more_rows = False
            self._show_empty_state(
                icon_name="folder-open.svg",
                title="No music folders yet",
                body="Add one or more folders to build your library and start browsing albums.",
                action_text="Open Settings",
                action_key="configure-folders",
            )
            return

        sort_order = "desc" if self._sort_order == Qt.SortOrder.DescendingOrder else "asc"
        if self._album_artist_name is not None:
            rows = get_album_rows_by_album_artist(
                db=self.app_state.db,
                album_artist_name=self._album_artist_name,
                search_query=self._search,
                limit=self._page_size + 1,
                offset=0 if reset else self._loaded_db_rows,
                sort_column=self._sort_column,
                sort_order=sort_order,
            )
        else:
            rows = get_album_rows(
                db=self.app_state.db,
                search_query=self._search,
                artist_id=self._artist_id,
                artist_ids=self._artist_ids,
                limit=self._page_size + 1,
                offset=0 if reset else self._loaded_db_rows,
                sort_column=self._sort_column,
                sort_order=sort_order,
            )
        self._has_more_rows = len(rows) > self._page_size
        visible_rows = rows[: self._page_size]
        ui_rows: list[AlbumListRow] = []
        if reset:
            self.model.setRowCount(0)
            self._loaded_db_rows = 0
            self._unknown_album_ids = []
            self._unknown_track_count = 0
            self._unknown_artist_names = set()
        self._loaded_db_rows += len(visible_rows)
        for r in visible_rows:
            album_id = int(r["album_id"])
            album_name = r["album_name"] or ""
            artist_name = r.get("artist_name") or None
            display_album = display_album_name(album_name)
            display_artist = display_artist_name(artist_name)

            if display_album == "N/A":
                self._unknown_album_ids.append(album_id)
                self._unknown_track_count += int(r.get("track_count") or 0)
                if display_artist != "N/A":
                    self._unknown_artist_names.add(display_artist)
                continue

            ui_rows.append(
                AlbumListRow(
                    album_ids=(album_id,),
                    album=display_album,
                    artist=display_artist,
                    track_count=int(r.get("track_count") or 0),
                )
            )
        self._append_rows(ui_rows, reset=reset)
        self._sync_unknown_bucket()
        self._loading_more = False
        self._update_header()
        if self.model.rowCount():
            self._show_table()
        elif self._artist_id is not None or self._artist_ids or self._album_artist_name:
            self._show_empty_state(
                icon_name="audio-lines.svg",
                title="No albums for this artist",
                body="This artist scope does not contain any albums with the current library metadata.",
                action_text=None,
                action_key="",
            )
        elif self._search.strip():
            self._show_empty_state(
                icon_name="search-x.svg",
                title="No albums match your search",
                body="Try a different search term or clear the current search to show more albums.",
                action_text="Clear Search",
                action_key="clear-search",
            )
        else:
            self._show_empty_state(
                icon_name="audio-lines.svg",
                title="No albums found",
                body="Try refreshing the library or reviewing your scan exclusions.",
                action_text="Refresh Library",
                action_key="refresh-library",
            )

    def set_rows(self, rows: Iterable[AlbumListRow]):
        self.model.setRowCount(0)
        for r in rows:
            items = [
                build_text_item(r.album, r.album_ids),
                build_text_item(display_artist_name(r.artist), r.album_ids),
                build_text_item(str(r.track_count), r.album_ids, align=Qt.AlignmentFlag.AlignCenter),
            ]
            self.model.appendRow(items)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    def _append_rows(self, rows: Iterable[AlbumListRow], *, reset: bool = False) -> None:
        if reset:
            self.model.setRowCount(0)
        for r in rows:
            items = [
                build_text_item(r.album, r.album_ids),
                build_text_item(display_artist_name(r.artist), r.album_ids),
                build_text_item(str(r.track_count), r.album_ids, align=Qt.AlignmentFlag.AlignCenter),
            ]
            self.model.appendRow(items)

    def show_album_tracks(self, album_id: int | list[int] | tuple[int, ...], album_name: str = "") -> None:
        album_ids = [int(v) for v in album_id] if isinstance(album_id, (list, tuple)) else [int(album_id)]
        self._detail_album_id = album_ids[0] if len(album_ids) == 1 else -1
        self._detail_album_name = display_album_name(album_name)
        self.track_list.setArtistFilter(None)
        self.track_list.setAlbumFilterLabel(self._detail_album_name)
        self.track_list.setAlbumFilter(album_ids if len(album_ids) > 1 else album_ids[0])
        self.stack.setCurrentWidget(self.track_list)
        self._update_header()

    def _update_header(self) -> None:
        if self.stack.currentWidget() is self.track_list:
            self.header_bar.show()
            self.header_label.setText(f"Album: {self._detail_album_name or 'N/A'}")
            return
        if self._album_artist_name is not None:
            self.header_bar.show()
            self.header_label.setText(f"Album Artist: {display_artist_name(self._album_artist_name)}")
            return
        if self._artist_id is not None or self._artist_ids:
            self.header_bar.show()
            self.header_label.setText(f"Artist: {display_artist_name(self._artist_name)}")
            return
        self.header_bar.hide()
        self.header_label.setText("")

    def _on_double_click(self, index: QModelIndex):
        if not index.isValid():
            return
        album_id = self.model.index(index.row(), 0).data(Qt.ItemDataRole.UserRole)
        album_name = self.model.index(index.row(), 0).data(Qt.ItemDataRole.DisplayRole) or ""
        album_ids = normalize_id_bucket(album_id)
        if not album_ids:
            return
        self.navigateRequested.emit(self._album_route(album_ids, str(album_name)))

    def _on_context_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        sm = self.table.selectionModel()
        if sm is not None and not sm.isRowSelected(idx.row(), idx.parent()):
            sm.setCurrentIndex(idx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)

        album_id = self.model.index(idx.row(), 0).data(Qt.ItemDataRole.UserRole)
        album_ids = normalize_id_bucket(album_id)
        if not album_ids:
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
            self.navigateRequested.emit(self._album_route(album_ids, str(album_name)))

    def _apply_styles(self):
        self.setStyleSheet(load_stylesheet("data_table.qss", table_name="AlbumTable"))

    def _album_route(self, album_ids: tuple[int, ...], album_name: str) -> LibraryRoute:
        if self._route_tab == "artists":
            artist_ids = tuple(self._artist_ids or ([self._artist_id] if self._artist_id is not None else []))
            return artists_album(artist_ids, album_ids, artist_label=self._artist_name, album_label=album_name)
        if self._route_tab == "album_artists":
            return album_artists_album(album_ids, artist_label=self._artist_name, album_label=album_name)
        return albums_detail(album_ids, label=album_name)

    def _handle_track_route(self, route: LibraryRoute) -> None:
        if route.tab == "tracks":
            if route.mode == "artist":
                self.navigateRequested.emit(artists_detail(route.artist_ids, label=route.artist_label))
                return
            if route.mode == "album":
                self.navigateRequested.emit(self._album_route(route.album_ids, route.album_label))
                return
        self.navigateRequested.emit(route)

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
        if not self._unknown_album_ids:
            row = self._find_unknown_row()
            if row >= 0:
                self.model.removeRow(row)
            return

        bucket_artist = "N/A" if len(self._unknown_artist_names) != 1 else next(iter(self._unknown_artist_names))
        row = self._find_unknown_row()
        if row < 0:
            self.model.appendRow(
                [
                    build_text_item("N/A", tuple(self._unknown_album_ids)),
                    build_text_item(bucket_artist, tuple(self._unknown_album_ids)),
                    build_text_item(str(self._unknown_track_count), tuple(self._unknown_album_ids), align=Qt.AlignmentFlag.AlignCenter),
                ]
            )
            return

        self.model.item(row, 0).setData(tuple(self._unknown_album_ids), Qt.ItemDataRole.UserRole)
        self.model.item(row, 1).setData(tuple(self._unknown_album_ids), Qt.ItemDataRole.UserRole)
        self.model.item(row, 2).setData(tuple(self._unknown_album_ids), Qt.ItemDataRole.UserRole)
        self.model.item(row, 1).setText(bucket_artist)
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
