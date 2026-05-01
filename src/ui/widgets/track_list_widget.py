# ui/track_list_widget.py
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time
from typing import Sequence

from PySide6.QtCore import QEvent, Signal, Qt, QItemSelectionModel, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from db.database import get_directories, get_duplicate_track_ids, get_track_by_id, get_track_rows
from ui.library_routes import LibraryRoute, tracks_album, tracks_artist
from ui.widgets.empty_state_widget import EmptyStateWidget
from ui.models.track_table_model import TrackTableModel
from ui.delegates.actions_delegate import ActionsDelegate
from ui.delegates.track_info_delegate import TrackInfoDelegate
from ui.spacing import set_layout_spacing
from ui.style_loader import load_stylesheet
from ui.widgets.sortable_header_view import SortableHeaderView
from ui.widgets.library_table_utils import should_load_more
from ui.widgets.track_list_rows import build_track_list_rows
from core.tracklist_models import DownloadState, LyricsState


TRACK_DURATION_COLUMN_WIDTH = 92
TRACK_LYRICS_COLUMN_WIDTH = 118
TRACK_ACTIONS_COLUMN_WIDTH = 142


class TrackListWidget(QWidget):
    previewTrack = Signal(int)    # track_id
    playTrack = Signal(int)       # track_id
    refreshTrack = Signal(int)    # track_id
    bulkRefreshRequested = Signal(list)  # track_ids
    downloadLyrics = Signal(int)  # track_id
    exportLyricsFiles = Signal(int)  # track_id
    importLyricsFile = Signal(int, str)  # track_id, file_path
    bulkDownloadRequested = Signal(list, str)  # track_ids, mode
    bulkPublishRequested = Signal(list, bool)   # track_ids, is_synced
    openArtist = Signal(int)
    openAlbum = Signal(int)
    navigateRequested = Signal(object)
    markInstrumental = Signal(list)        # list[int]
    unmarkInstrumental = Signal(list)      # list[int]
    clearFiltersRequested = Signal()
    configureFoldersRequested = Signal()

    def __init__(self, app_state, *, show_bulk_context_actions: bool = True):
        super().__init__()
        self.app_state = app_state
        self._show_bulk_context_actions = show_bulk_context_actions
        self._active = True
        self._page_size = 250
        self._search = ""
        self._filters = dict(
            synced=True,
            plain=True,
            instrumental=False,
            none=True,
            unsaved=False,
        )
        self._artist_id: int | None = None
        self._album_id: int | None = None
        self._artist_ids: list[int] | None = None
        self._album_ids: list[int] | None = None
        self._scope_label: str = ""
        self._scope_banner_enabled = True
        self._download_states: dict[int, DownloadState] = {}
        self._sort_column = 0
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._has_more_rows = False
        self._loading_more = False
        self._duplicate_ids: set[int] = set()
        self._ui_scale = 1.0

        self.scope_bar = QWidget()
        self.scope_bar.setObjectName("TrackScopeBar")
        scope_layout = QHBoxLayout(self.scope_bar)
        scope_layout.setContentsMargins(10, 6, 10, 6)
        scope_layout.setSpacing(8)
        self.scope_label = QLabel("")
        self.scope_label.setObjectName("TrackScopeLabel")
        self.scope_clear_btn = QPushButton("Clear Filter")
        self.scope_clear_btn.setObjectName("TrackScopeClearButton")
        self.scope_clear_btn.clicked.connect(self.clearFiltersRequested.emit)
        scope_layout.addWidget(self.scope_label, 1)
        scope_layout.addWidget(self.scope_clear_btn)
        self.scope_bar.hide()

        self.stack = QStackedWidget()
        self.table = QTableView()
        self.model = TrackTableModel([])
        self.table.setModel(self.model)
        self.header = SortableHeaderView(
            Qt.Orientation.Horizontal,
            self.table,
            default_sort_column=0,
            default_sort_order=Qt.SortOrder.AscendingOrder,
            non_sortable_columns={3},
        )
        self.table.setHorizontalHeader(self.header)

        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setMouseTracking(True)
        self.table.viewport().setMouseTracking(True)
        self.table.setAcceptDrops(True)
        self.table.viewport().setAcceptDrops(True)
        self.table.viewport().installEventFilter(self)
        self._suppress_left_click_until = 0.0
        self.table.setSortingEnabled(False)
        self.header.setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.header.sortIndicatorChanged.connect(self._on_sort_changed)
        self.table.verticalScrollBar().valueChanged.connect(self._maybe_load_more)

        self.header.setStretchLastSection(False)
        self.header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setObjectName("TrackTable")
        self._apply_column_widths()

        self.table.verticalHeader().setDefaultSectionSize(44)

        self._apply_styles()

        # Actions delegate (Download button in last column)
        self.actions = ActionsDelegate(self.table)
        self.actions.refreshClicked.connect(self.refreshTrack.emit)
        self.actions.downloadClicked.connect(self.downloadLyrics.emit)
        self.table.setItemDelegateForColumn(3, self.actions)

        self.track_info = TrackInfoDelegate(self.table)
        self.track_info.artistClicked.connect(self._emit_artist_navigation)
        self.track_info.albumClicked.connect(self._emit_album_navigation)
        self.table.setItemDelegateForColumn(0, self.track_info)

        # Double click -> play
        self.table.doubleClicked.connect(self._on_double_click)

        # Right-click context menu
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)

        self.empty_state = EmptyStateWidget()
        self.empty_state.actionTriggered.connect(self._on_empty_state_action)

        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty_state)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.scope_bar)
        layout.addWidget(self.stack)

        self._empty_action = ""

    def set_ui_scale(self, scale: float) -> None:
        self._ui_scale = max(0.85, min(1.5, float(scale or 1.0)))
        self.table.verticalHeader().setDefaultSectionSize(int(round(44 * self._ui_scale)))
        self._apply_column_widths()
        if hasattr(self.actions, "set_ui_scale"):
            self.actions.set_ui_scale(self._ui_scale)

    def _apply_column_widths(self) -> None:
        self.table.setColumnWidth(1, int(round(TRACK_DURATION_COLUMN_WIDTH * self._ui_scale)))
        self.table.setColumnWidth(2, int(round(TRACK_LYRICS_COLUMN_WIDTH * self._ui_scale)))
        self.table.setColumnWidth(3, int(round(TRACK_ACTIONS_COLUMN_WIDTH * self._ui_scale)))

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
        # Optional: typing search exits artist/album drill-down
        self._artist_id = None
        self._album_id = None
        self._artist_ids = None
        self._album_ids = None
        self._scope_label = ""
        self._update_scope_banner()
        if self._active:
            self.refresh()

    def setFilters(self, synced: bool, plain: bool, instrumental: bool, none_: bool, unsaved: bool = False):
        self._filters = dict(synced=synced, plain=plain, instrumental=instrumental, none=none_, unsaved=unsaved)
        if self._active:
            self.refresh()

    def setScopeBannerEnabled(self, enabled: bool) -> None:
        self._scope_banner_enabled = bool(enabled)
        self._update_scope_banner()

    def apply_route(self, route: LibraryRoute) -> None:
        if route.tab != "tracks":
            return

        if route.mode == "root":
            self._artist_id = None
            self._album_id = None
            self._artist_ids = None
            self._album_ids = None
            self._scope_label = ""
        elif route.mode == "artist":
            self._album_id = None
            self._album_ids = None
            if len(route.artist_ids) > 1:
                values = [int(v) for v in route.artist_ids]
                self._artist_ids = values
                self._artist_id = None
            else:
                self._artist_id = int(route.artist_ids[0]) if route.artist_ids else None
                self._artist_ids = None
            self._scope_label = f"Artist: {route.artist_label}" if route.artist_label else "Artist filter active"
        elif route.mode == "album":
            self._artist_id = None
            self._artist_ids = None
            if len(route.album_ids) > 1:
                values = [int(v) for v in route.album_ids]
                self._album_ids = values
                self._album_id = None
            else:
                self._album_id = int(route.album_ids[0]) if route.album_ids else None
                self._album_ids = None
            self._scope_label = f"Album: {route.album_label}" if route.album_label else "Album filter active"

        self._update_scope_banner()
        if self._active:
            self.refresh()

    def refresh(self):
        self._load_rows(reset=True)

    def _load_rows(self, *, reset: bool) -> None:
        db = self.app_state.db
        directories = get_directories(db)
        if not directories:
            self.model.set_rows([])
            self._has_more_rows = False
            self._show_empty_state(
                icon_name="folder-open.svg",
                title="No music folders yet",
                body="Add one or more folders to build your library and start browsing tracks.",
                action_text="Open Music Folders",
                action_key="configure-folders",
            )
            return

        rows = get_track_rows(
            db=db,
            search_query=self._search,
            synced_lyrics_tracks=self._filters["synced"],
            plain_lyrics_tracks=self._filters["plain"],
            instrumental_tracks=self._filters["instrumental"],
            no_lyrics_tracks=self._filters["none"],
            unsaved_draft_only=self._filters.get("unsaved", False),
            limit=self._page_size + 1,
            offset=0 if reset else self.model.rowCount(),
            artist_id=self._artist_id,
            album_id=self._album_id,
            artist_ids=self._artist_ids,
            album_ids=self._album_ids,
            sort_column=self._sort_column,
            sort_order="desc" if self._sort_order == Qt.SortOrder.DescendingOrder else "asc",
        )
        self._has_more_rows = len(rows) > self._page_size
        visible_rows = rows[: self._page_size]

        if reset:
            self._duplicate_ids = get_duplicate_track_ids(db)

        ui_rows = build_track_list_rows(visible_rows, self._download_states, self._duplicate_ids)

        if reset:
            self.model.set_rows(ui_rows)
        else:
            self.model.append_rows(ui_rows)
        self._loading_more = False
        if self.model.rowCount():
            self.stack.setCurrentWidget(self.table)
        else:
            self._show_empty_state(
                icon_name="search-x.svg",
                title="No tracks match the current filters",
                body="Try clearing the search or relaxing the lyric filters to show more tracks.",
                action_text="Clear Filters",
                action_key="clear-filters",
            )

    def current_track_id(self) -> int | None:
        sm = self.table.selectionModel()
        if sm is None or not sm.hasSelection():
            return None
        idxs = sm.selectedRows()
        if not idxs:
            return None
        try:
            return int(self.model.track_id_at(idxs[0].row()))
        except (ValueError, IndexError, AttributeError):
            return None

    # -------------------------
    # UI Events
    # -------------------------
    def _on_double_click(self, index):
        if not index.isValid():
            return
        track_id = self.model.track_id_at(index.row())
        if track_id is not None:
            self.playTrack.emit(int(track_id))

    def _on_selection_changed(self, *_args) -> None:
        track_id = self.selected_track_id()
        if track_id is not None:
            self.previewTrack.emit(int(track_id))

    def _on_context_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return

        # If clicked row isn't selected, select it (common UX)
        sm = self.table.selectionModel()
        if sm is not None and not sm.isRowSelected(idx.row(), idx.parent()):
            sm.setCurrentIndex(idx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)

        selected_ids = self.selected_track_ids()
        if not selected_ids:
            return

        menu = QMenu(self)
        menu.setObjectName("TrackContextMenu")
        current_track_id = self.model.track_id_at(idx.row())
        has_focused_track = current_track_id is not None

        def add_section(title: str, detail: str = ""):
            action = QWidgetAction(menu)
            header = QWidget(menu)
            header.setObjectName("ContextMenuSection")
            header_layout = QVBoxLayout(header)
            set_layout_spacing(header_layout, margins=(10, 6, 10, 4), spacing=1)
            title_label = QLabel(title.upper())
            title_label.setObjectName("ContextMenuSectionTitle")
            header_layout.addWidget(title_label)
            if detail:
                detail_label = QLabel(detail)
                detail_label.setObjectName("ContextMenuSectionDetail")
                header_layout.addWidget(detail_label)
            action.setDefaultWidget(header)
            menu.addAction(action)
            return action

        count = len(selected_ids)
        count_text = f"{count} track selected" if count == 1 else f"{count} tracks selected"
        add_section("Selection", count_text)
        act_refresh_selected = menu.addAction(f"Refresh selected from disk ({count})")
        act_play = menu.addAction("Play now")
        act_play.setEnabled(has_focused_track)

        menu.addSeparator()
        add_section("Focused Track")
        act_open_folder = menu.addAction("Open containing folder")
        act_dl = menu.addAction("Download lyrics")
        act_export = menu.addAction("Export lyrics files")
        act_open_folder.setEnabled(has_focused_track)
        act_dl.setEnabled(has_focused_track)
        act_export.setEnabled(has_focused_track)

        count_suffix = f"({len(selected_ids)})"
        if self._show_bulk_context_actions:
            menu.addSeparator()
            add_section("Download Selection")
            act_dl_selected = menu.addAction(f"Use current mode {count_suffix}")
            act_dl_synced = menu.addAction(f"Synced only {count_suffix}")
            act_dl_plain = menu.addAction(f"Plain only {count_suffix}")

            menu.addSeparator()
            add_section("Lyrics State")
            act_instr = menu.addAction(f"Mark as instrumental {count_suffix}")
            act_uninstr = menu.addAction(f"Unmark instrumental {count_suffix}")

            menu.addSeparator()
            add_section("Publish Selection")
            act_pub_synced = menu.addAction(f"Publish synced {count_suffix}")
            act_pub_plain = menu.addAction(f"Publish plain {count_suffix}")
        else:
            act_dl_selected = None
            act_dl_synced = None
            act_dl_plain = None
            act_instr = None
            act_uninstr = None
            act_pub_synced = None
            act_pub_plain = None

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            self._suppress_next_table_left_click()
            return
        if chosen == act_play:
            if current_track_id is not None:
                self.playTrack.emit(int(current_track_id))
        elif chosen == act_refresh_selected:
            self.bulkRefreshRequested.emit(selected_ids)
        elif chosen == act_open_folder:
            if current_track_id is not None:
                self._open_track_folder(int(current_track_id))
        elif chosen == act_dl:
            if current_track_id is not None:
                self.downloadLyrics.emit(int(current_track_id))
        elif chosen == act_export:
            if current_track_id is not None:
                self.exportLyricsFiles.emit(int(current_track_id))
        elif chosen == act_dl_selected:
            self.bulkDownloadRequested.emit(selected_ids, "use_global")
        elif chosen == act_dl_synced:
            self.bulkDownloadRequested.emit(selected_ids, "synced_only")
        elif chosen == act_dl_plain:
            self.bulkDownloadRequested.emit(selected_ids, "plain_only")
        elif chosen == act_instr:
            self.markInstrumental.emit(selected_ids)
        elif chosen == act_uninstr:
            self.unmarkInstrumental.emit(selected_ids)
        elif chosen == act_pub_synced:
            self.bulkPublishRequested.emit(selected_ids, True)
        elif chosen == act_pub_plain:
            self.bulkPublishRequested.emit(selected_ids, False)

    def eventFilter(self, watched, event):
        if watched is self.table.viewport() and event.type() in {
            QEvent.Type.DragEnter,
            QEvent.Type.DragMove,
            QEvent.Type.Drop,
        }:
            lyrics_path = self._lyrics_file_from_mime(event.mimeData())
            idx = self.table.indexAt(self._event_position(event))
            track_id = self.model.track_id_at(idx.row()) if idx.isValid() else None
            if lyrics_path and track_id is not None:
                event.acceptProposedAction()
                if event.type() == QEvent.Type.Drop:
                    self.importLyricsFile.emit(int(track_id), lyrics_path)
                return True

        if watched is self.table.viewport() and event.type() in {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
        }:
            if (
                event.button() == Qt.MouseButton.LeftButton
                and time.monotonic() < self._suppress_left_click_until
            ):
                event.accept()
                return True
        return super().eventFilter(watched, event)

    @staticmethod
    def _event_position(event):
        if hasattr(event, "position"):
            return event.position().toPoint()
        return event.pos()

    @staticmethod
    def _lyrics_file_from_mime(mime_data) -> str:
        if not mime_data.hasUrls():
            return ""
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if Path(path).suffix.lower() in {".lrc", ".txt"} and Path(path).is_file():
                return str(path)
        return ""

    def _suppress_next_table_left_click(self) -> None:
        self._suppress_left_click_until = time.monotonic() + 0.35

    def _open_track_folder(self, track_id: int) -> bool:
        track = get_track_by_id(self.app_state.db, int(track_id))
        file_path = str(track.file_path or "").strip()
        if not file_path:
            return False
        folder = Path(file_path).expanduser().parent
        if not str(folder) or not folder.exists():
            return False
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _emit_artist_navigation(self, artist_id: int) -> None:
        self.openArtist.emit(int(artist_id))
        self.navigateRequested.emit(tracks_artist((int(artist_id),)))

    def _emit_album_navigation(self, album_id: int) -> None:
        self.openAlbum.emit(int(album_id))
        self.navigateRequested.emit(tracks_album((int(album_id),)))

    def set_now_playing(self, track_id: int | None):
        if track_id is None:
            self.table.clearSelection()
            return

        row = self.model.row_for_track_id(track_id)
        if row < 0:
            return  # track not in current filtered view

        idx = self.model.index(row, 0)
        sm = self.table.selectionModel()
        if sm is None:
            return

        sm.setCurrentIndex(idx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        self.table.scrollTo(idx, QTableView.ScrollHint.PositionAtCenter)

    def current_queue_track_ids(self) -> list[int]:
        return self.model.all_track_ids()

    def selected_track_id(self) -> int | None:
        idx = self.table.currentIndex()
        if not idx.isValid():
            return None
        return self.model.track_id_at(idx.row())

    def setArtistFilter(self, artist_id: int | Sequence[int] | None):
        if isinstance(artist_id, Sequence) and not isinstance(artist_id, (str, bytes)):
            values = [int(v) for v in artist_id]
            self._artist_ids = values or None
            self._artist_id = values[0] if len(values) == 1 else None
        else:
            self._artist_id = int(artist_id) if artist_id is not None else None
            self._artist_ids = None
        if self._artist_id is None and self._artist_ids is None:
            self._scope_label = ""
        elif not self._scope_label.startswith("Artist: "):
            self._scope_label = "Artist filter active"
        self._update_scope_banner()
        if self._active:
            self.refresh()

    def setArtistFilterLabel(self, label: str) -> None:
        self._scope_label = f"Artist: {label}" if label else "Artist filter active"
        self._update_scope_banner()

    def setAlbumFilter(self, album_id: int | Sequence[int] | None):
        if isinstance(album_id, Sequence) and not isinstance(album_id, (str, bytes)):
            values = [int(v) for v in album_id]
            self._album_ids = values or None
            self._album_id = values[0] if len(values) == 1 else None
        else:
            self._album_id = int(album_id) if album_id is not None else None
            self._album_ids = None
        if self._album_id is None and self._album_ids is None:
            self._scope_label = ""
        elif not self._scope_label.startswith("Album: "):
            self._scope_label = "Album filter active"
        self._update_scope_banner()
        if self._active:
            self.refresh()

    def setAlbumFilterLabel(self, label: str) -> None:
        self._scope_label = f"Album: {label}" if label else "Album filter active"
        self._update_scope_banner()

    def selected_track_ids(self) -> list[int]:
        sm = self.table.selectionModel()
        if sm is None or not sm.hasSelection():
            return []
        ids: list[int] = []
        for idx in sm.selectedRows():
            tid = self.model.track_id_at(idx.row())
            if tid is not None:
                ids.append(int(tid))
        # keep stable order (row order)
        return ids

    def restore_selection(self, track_ids: set[int]):
        if not track_ids:
            return
        sm = self.table.selectionModel()
        if sm is None:
            return

        sm.clearSelection()

        first_idx = None
        for row in range(self.model.rowCount()):
            tid = self.model.track_id_at(row)
            if tid is None:
                continue
            if int(tid) in track_ids:
                idx = self.model.index(row, 0)
                sm.select(idx, QItemSelectionModel.Select | QItemSelectionModel.Rows)
                if first_idx is None:
                    first_idx = idx

        if first_idx is not None:
            sm.setCurrentIndex(first_idx, QItemSelectionModel.Current | QItemSelectionModel.Rows)
            self.table.scrollTo(first_idx, QTableView.ScrollHint.PositionAtCenter)

    def _apply_styles(self):
        self.setStyleSheet(load_stylesheet("data_table.qss", table_name="TrackTable"))

    def _update_scope_banner(self) -> None:
        if not self._scope_banner_enabled:
            self.scope_bar.hide()
            self.scope_label.setText("")
            return
        active = bool(
            self._artist_id is not None
            or self._album_id is not None
            or self._artist_ids
            or self._album_ids
        )
        self.scope_bar.setVisible(active)
        if not active:
            self.scope_label.setText("")
            return
        detail = self._scope_label.strip() or "Library filter active"
        self.scope_label.setText(f"Showing a filtered view. {detail}")

    def _show_empty_state(self, *, icon_name: str, title: str, body: str, action_text: str, action_key: str) -> None:
        self._empty_action = action_key
        self.empty_state.configure(
            icon_name=icon_name,
            title=title,
            body=body,
            action_text=action_text,
        )
        self.stack.setCurrentWidget(self.empty_state)

    def _on_empty_state_action(self) -> None:
        if self._empty_action == "clear-filters":
            self.clearFiltersRequested.emit()
        elif self._empty_action == "configure-folders":
            self.configureFoldersRequested.emit()

    def set_download_state(self, track_id: int, state: str | DownloadState) -> None:
        normalized = state if isinstance(state, DownloadState) else DownloadState(str(state))
        self._download_states[int(track_id)] = normalized
        row = self.model.row_for_track_id(int(track_id))
        if row < 0:
            return
        current = self.model._rows[row]
        self.model._rows[row] = replace(current, download_state=normalized)
        idx = self.model.index(row, 3)
        self.model.dataChanged.emit(idx, idx, [Qt.DisplayRole, Qt.UserRole])

    def set_dirty_lyrics_state(self, track_id: int, has_dirty_lyrics: bool) -> None:
        row = self.model.row_for_track_id(int(track_id))
        if row < 0:
            return
        current = self.model._rows[row]
        self.model._rows[row] = replace(current, has_dirty_lyrics=bool(has_dirty_lyrics))
        idx = self.model.index(row, 2)
        self.model.dataChanged.emit(idx, idx, [Qt.DisplayRole, Qt.ForegroundRole, Qt.FontRole, Qt.UserRole])

    def update_track_lyrics_state(self, track_id: int, lyrics_state: LyricsState) -> None:
        row = self.model.row_for_track_id(int(track_id))
        if row < 0:
            return
        current = self.model._rows[row]
        self.model._rows[row] = replace(current, lyrics_state=lyrics_state, has_dirty_lyrics=False)
        idx = self.model.index(row, 2)
        self.model.dataChanged.emit(idx, idx, [Qt.DisplayRole, Qt.ForegroundRole, Qt.FontRole, Qt.UserRole])

    def get_download_state(self, track_id: int) -> DownloadState:
        return self._download_states.get(int(track_id), DownloadState.IDLE)

    def _on_sort_changed(self, column: int, order: Qt.SortOrder) -> None:
        if column == 3:
            return
        self._sort_column = int(column)
        self._sort_order = order
        if self._active:
            self.refresh()

    def _maybe_load_more(self, value: int) -> None:
        scroll = self.table.verticalScrollBar()
        if not should_load_more(
            has_more_rows=self._has_more_rows,
            loading_more=self._loading_more,
            is_browser_visible=True,
            value=value,
            maximum=scroll.maximum(),
        ):
            return
        self._loading_more = True
        try:
            self._load_rows(reset=False)
        finally:
            self._loading_more = False
