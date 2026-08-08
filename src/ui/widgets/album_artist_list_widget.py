"""
AlbumArtistListWidget
=====================
Displays the library grouped by **album artist** (the ``album_artist_name``
field on the ``albums`` table, i.e. the ID3v2 TPE2 / FLAC ALBUMARTIST tag).

This is distinct from the Artists tab which groups by the *track-level* artist
(TPE1 / ARTIST tag).  The key difference matters for:

* "Various Artists" compilations — the album artist is "Various Artists" while
  individual tracks carry the actual performer's name.
* "Main Artist feat. Featured Artist" — the album artist is the main artist
  while the track artist includes the featured name.
"""
from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt, Signal, QModelIndex, QItemSelectionModel
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QHeaderView,
    QMenu,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from db.database import get_directories
from ui.style_loader import load_stylesheet
from ui.library_routes import LibraryRoute, album_artists_album, album_artists_detail
from ui.widgets.empty_state_widget import EmptyStateWidget
from ui.widgets.library_rows import ArtistListRow
from ui.widgets.library_table_utils import (
    build_text_item,
    display_artist_name,
    find_display_row,
    should_load_more,
)
from ui.widgets.sortable_header_view import SortableHeaderView
from ui.widgets.album_list_widget import AlbumListWidget


class AlbumArtistListWidget(QWidget):
    """Top-level widget for the Album Artists navigation tab."""

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
        self._page_size = 200
        self._sort_column = 0
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._has_more_rows = False
        self._loading_more = False
        self._loaded_db_rows = 0
        self._ui_scale = 1.0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        # --- Page 0: flat table of album artists ---
        self.browser_page = QWidget()
        browser_layout = QVBoxLayout(self.browser_page)
        browser_layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableView()
        self.model = QStandardItemModel(0, 3, self)
        self.model.setHorizontalHeaderLabels(["Album Artist", "Albums", "Tracks"])
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
        self.header.setStretchLastSection(False)
        self.header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
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

        # --- Page 1: album browser (scoped by album artist name) ---
        self.album_browser = AlbumListWidget(self.app_state)
        self.album_browser.setRouteTab("album_artists")
        self.album_browser.playTrack.connect(self.playTrack.emit)
        self.album_browser.previewTrack.connect(self.previewTrack.emit)
        self.album_browser.refreshTrack.connect(self.refreshTrack.emit)
        self.album_browser.bulkRefreshRequested.connect(self.bulkRefreshRequested.emit)
        self.album_browser.downloadLyrics.connect(self.downloadLyrics.emit)
        self.album_browser.exportLyricsFiles.connect(self.exportLyricsFiles.emit)
        self.album_browser.importLyricsFile.connect(self.importLyricsFile.emit)
        self.album_browser.bulkDownloadRequested.connect(self.bulkDownloadRequested.emit)
        self.album_browser.openArtist.connect(self.openArtist.emit)
        self.album_browser.openAlbum.connect(self.openAlbum.emit)
        self.album_browser.navigateRequested.connect(self.navigateRequested.emit)
        self.album_browser.markInstrumental.connect(self.markInstrumental.emit)
        self.album_browser.unmarkInstrumental.connect(self.unmarkInstrumental.emit)
        self.album_browser.clearFiltersRequested.connect(self.clearFiltersRequested.emit)
        self.album_browser.clearSearchRequested.connect(self.clearSearchRequested.emit)
        self.album_browser.refreshLibraryRequested.connect(self.refreshLibraryRequested.emit)
        self.album_browser.configureFoldersRequested.connect(self.configureFoldersRequested.emit)
        self.stack.addWidget(self.album_browser)

        self.table.doubleClicked.connect(self._on_double_click)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)

        self._apply_styles()
        self._empty_action = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_ui_scale(self, scale: float) -> None:
        self._ui_scale = max(0.85, min(1.5, float(scale or 1.0)))
        self.table.verticalHeader().setDefaultSectionSize(int(round(30 * self._ui_scale)))
        self.album_browser.set_ui_scale(self._ui_scale)

    def apply_current_palette(self) -> None:
        self.table.viewport().update()
        self.table.update()
        self.album_browser.apply_current_palette()

    def setActive(self, active: bool) -> None:
        self._active = active
        self.setVisible(active)
        if active:
            self.refresh()

    def setSearchValue(self, text: str) -> None:
        self._search = text or ""
        if self._active and self.stack.currentWidget() is self.browser_page:
            self.refresh()

    def apply_route(self, route: LibraryRoute) -> None:
        if route.tab != "album_artists":
            return
        if route.mode == "root":
            self._return_to_album_artists()
            return
        if route.mode == "artist":
            self.show_album_artist_albums(route.artist_label)
            return
        if route.mode == "artist_album":
            self.show_album_artist_albums(route.artist_label)
            self.show_album_tracks(
                list(route.album_ids) if len(route.album_ids) > 1 else (route.album_ids[0] if route.album_ids else None),
                route.album_label,
            )
            return

    def refresh(self) -> None:
        self._load_rows(reset=True)

    def set_download_state(self, track_id: int, state: str) -> None:
        self.album_browser.set_download_state(track_id, state)

    def set_dirty_lyrics_state(self, track_id: int, has_dirty_lyrics: bool) -> None:
        self.album_browser.set_dirty_lyrics_state(track_id, has_dirty_lyrics)

    def update_track_lyrics_state(self, track_id: int, lyrics_state) -> None:
        self.album_browser.update_track_lyrics_state(track_id, lyrics_state)

    def get_download_state(self, track_id: int) -> str:
        return self.album_browser.get_download_state(track_id)

    def show_album_artist_albums(self, album_artist_name: str) -> None:
        """Drill into a specific album artist and show their albums."""
        self.album_browser.setAlbumArtistScope(album_artist_name)
        self.stack.setCurrentWidget(self.album_browser)

    def show_album_tracks(self, album_id, album_name: str = "") -> None:
        self.album_browser.show_album_tracks(album_id, album_name)
        self.stack.setCurrentWidget(self.album_browser)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_rows(self, *, reset: bool) -> None:
        from db.database import get_album_artist_rows

        directories = get_directories(self.app_state.db)
        if not directories:
            self.model.setRowCount(0)
            self._has_more_rows = False
            self._show_empty_state(
                icon_name="folder-open.svg",
                title="No music folders yet",
                body="Add one or more folders to build your library and start browsing album artists.",
                action_text="Open Settings",
                action_key="configure-folders",
            )
            return

        rows = get_album_artist_rows(
            self.app_state.db,
            self._search,
            limit=self._page_size + 1,
            offset=0 if reset else self._loaded_db_rows,
            sort_column=self._sort_column,
            sort_order="desc" if self._sort_order == Qt.SortOrder.DescendingOrder else "asc",
        )
        self._has_more_rows = len(rows) > self._page_size
        visible_rows = rows[: self._page_size]

        if reset:
            self.model.setRowCount(0)
            self._loaded_db_rows = 0
        self._loaded_db_rows += len(visible_rows)

        ui_rows: list[ArtistListRow] = []
        for r in visible_rows:
            name = r.get("album_artist_name") or ""
            display = display_artist_name(name)
            ui_rows.append(
                ArtistListRow(
                    # We store the name string in the artist_ids slot as a 0-tuple
                    # and use DisplayRole for navigation (string-keyed routing).
                    artist_ids=(0,),
                    artist=display or "N/A",
                    albums=int(r.get("album_count") or 0),
                    tracks=int(r.get("track_count") or 0),
                )
            )
        self._append_rows(ui_rows, reset=reset)
        self._loading_more = False

        if self.model.rowCount():
            self._show_table()
        elif self._search.strip():
            self._show_empty_state(
                icon_name="search-x.svg",
                title="No album artists match your search",
                body="Try a different search term or clear the current search to show more album artists.",
                action_text="Clear Search",
                action_key="clear-search",
            )
        else:
            self._show_empty_state(
                icon_name="audio-lines.svg",
                title="No album artists found",
                body="Try refreshing the library or reviewing your scan exclusions.",
                action_text="Refresh Library",
                action_key="refresh-library",
            )

    def _append_rows(self, rows: Iterable[ArtistListRow], *, reset: bool = False) -> None:
        if reset:
            self.model.setRowCount(0)
        for r in rows:
            # Store the artist name string (not IDs) in UserRole so we can look it up on click.
            name_item = QStandardItem(r.artist)
            name_item.setData(r.artist, Qt.ItemDataRole.UserRole)  # string key
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            albums_item = build_text_item(str(r.albums), (0,), align=Qt.AlignmentFlag.AlignCenter)
            albums_item.setData(r.artist, Qt.ItemDataRole.UserRole)
            tracks_item = build_text_item(str(r.tracks), (0,), align=Qt.AlignmentFlag.AlignCenter)
            tracks_item.setData(r.artist, Qt.ItemDataRole.UserRole)
            self.model.appendRow([name_item, albums_item, tracks_item])

    def _return_to_album_artists(self) -> None:
        self.album_browser.clearArtistScope()
        self.stack.setCurrentWidget(self.browser_page)
        if self._active:
            self.refresh()

    def _on_double_click(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        name = self.model.index(index.row(), 0).data(Qt.ItemDataRole.UserRole)
        if name:
            self.navigateRequested.emit(album_artists_detail(label=str(name)))

    def _on_context_menu(self, pos) -> None:
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        sm = self.table.selectionModel()
        if sm is not None and not sm.isRowSelected(idx.row(), idx.parent()):
            sm.setCurrentIndex(idx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)

        name = self.model.index(idx.row(), 0).data(Qt.ItemDataRole.UserRole)
        if not name:
            return

        menu = QMenu(self)
        info = menu.addAction(str(name))
        info.setEnabled(False)
        menu.addSeparator()
        act_open = menu.addAction("Open album artist")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == act_open:
            self.navigateRequested.emit(album_artists_detail(label=str(name)))

    def _apply_styles(self) -> None:
        self.setStyleSheet(load_stylesheet("data_table.qss", table_name="ArtistTable"))

    def _show_table(self) -> None:
        self.table.show()
        self.empty_state.hide()

    def _show_empty_state(self, *, icon_name: str, title: str, body: str, action_text: str | None, action_key: str) -> None:
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
