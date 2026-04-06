# ui/track_list_widget.py
from __future__ import annotations

from PySide6.QtCore import Signal, Qt, QItemSelectionModel, QSortFilterProxyModel
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QMenu

from ui.models.track_table_model import TrackTableModel
from ui.delegates.actions_delegate import ActionsDelegate
from ui.style_loader import load_stylesheet
from ui.widgets.sortable_header_view import SortableHeaderView
from core.tracklist_models import TrackListRow
from db.database import get_track_rows


class TrackSortProxyModel(QSortFilterProxyModel):
    _LYRICS_ORDER = {
        "synced": 0,
        "plain": 1,
        "instrumental": 2,
        "none": 3,
    }

    def lessThan(self, left, right) -> bool:
        left_row = self.sourceModel().data(left, Qt.ItemDataRole.UserRole)
        right_row = self.sourceModel().data(right, Qt.ItemDataRole.UserRole)

        if left_row is None or right_row is None:
            return super().lessThan(left, right)

        column = left.column()
        if column == 0:
            left_key = ((left_row.artist or "").casefold(), left_row.title.casefold(), left_row.track_id)
            right_key = ((right_row.artist or "").casefold(), right_row.title.casefold(), right_row.track_id)
            return left_key < right_key
        if column == 1:
            left_key = (left_row.duration_s is None, left_row.duration_s or 0, left_row.track_id)
            right_key = (right_row.duration_s is None, right_row.duration_s or 0, right_row.track_id)
            return left_key < right_key
        if column == 2:
            left_key = (self._LYRICS_ORDER.get(left_row.lyrics_state, 99), left_row.title.casefold(), left_row.track_id)
            right_key = (self._LYRICS_ORDER.get(right_row.lyrics_state, 99), right_row.title.casefold(), right_row.track_id)
            return left_key < right_key

        return super().lessThan(left, right)


class TrackListWidget(QWidget):
    playTrack = Signal(int)       # track_id
    downloadLyrics = Signal(int)  # track_id
    markInstrumental = Signal(list)        # list[int]
    unmarkInstrumental = Signal(list)      # list[int]

    def __init__(self, app_state):
        super().__init__()
        self.app_state = app_state
        self._active = True
        self._search = ""
        self._filters = dict(
            synced=True,
            plain=True,
            instrumental=False,
            none=True,
        )
        self._artist_id: int | None = None
        self._album_id: int | None = None

        self.table = QTableView()
        self.model = TrackTableModel([])
        self.proxy_model = TrackSortProxyModel(self)
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setDynamicSortFilter(True)
        self.table.setModel(self.proxy_model)
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
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        self.table.setColumnWidth(0, 520)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 140)
        self.header.setStretchLastSection(True)
        self.table.setObjectName("TrackTable")

        self.table.verticalHeader().setDefaultSectionSize(24)

        self._apply_styles()

        # Actions delegate (Download button in last column)
        self.actions = ActionsDelegate(self.table)
        self.actions.downloadClicked.connect(self.downloadLyrics.emit)
        self.table.setItemDelegateForColumn(3, self.actions)

        # Double click -> play
        self.table.doubleClicked.connect(self._on_double_click)

        # Right-click context menu
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)

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
        if self._active:
            self.refresh()

    def setFilters(self, synced: bool, plain: bool, instrumental: bool, none_: bool):
        self._filters = dict(synced=synced, plain=plain, instrumental=instrumental, none=none_)
        if self._active:
            self.refresh()

    def refresh(self):
        db = self.app_state.db
        rows = get_track_rows(
            db=db,
            search_query=self._search,
            synced_lyrics_tracks=self._filters["synced"],
            plain_lyrics_tracks=self._filters["plain"],
            instrumental_tracks=self._filters["instrumental"],
            no_lyrics_tracks=self._filters["none"],
            artist_id=self._artist_id,
            album_id=self._album_id,
        )

        ui_rows: list[TrackListRow] = []
        for r in rows:
            instrumental = bool(r["instrumental"])
            lrc = r["lrc_lyrics"]
            txt = r["txt_lyrics"]

            if instrumental:
                state = "instrumental"
            elif lrc and lrc != "[au: instrumental]":
                state = "synced"
            elif txt:
                state = "plain"
            else:
                state = "none"

            dur = r["duration"]
            dur_s = int(round(dur)) if dur is not None else None

            ui_rows.append(
                TrackListRow(
                    track_id=int(r["id"]),
                    title=r["title"] or "",
                    artist=r["artist_name"],
                    duration_s=dur_s,
                    lyrics_state=state,
                )
            )

        self.model.set_rows(ui_rows)

    def current_track_id(self) -> int | None:
        sm = self.table.selectionModel()
        if sm is None or not sm.hasSelection():
            return None
        idxs = sm.selectedRows()
        if not idxs:
            return None
        row = self._source_row(idxs[0])
        try:
            return int(self.model.track_id_at(row))
        except Exception:
            return None

    # -------------------------
    # UI Events
    # -------------------------
    def _on_double_click(self, index):
        if not index.isValid():
            return
        row = self._source_row(index)
        track_id = self.model.track_id_at(row)
        if track_id is not None:
            self.playTrack.emit(int(track_id))

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
        act_play = menu.addAction("Play")
        act_dl = menu.addAction("Download lyrics")

        menu.addSeparator()
        act_instr = menu.addAction(f"Mark as instrumental ({len(selected_ids)})")
        act_uninstr = menu.addAction(f"Unmark instrumental ({len(selected_ids)})")

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == act_play:
            track_id = self.model.track_id_at(self._source_row(idx))
            if track_id is not None:
                self.playTrack.emit(int(track_id))
        elif chosen == act_dl:
            track_id = self.model.track_id_at(self._source_row(idx))
            if track_id is not None:
                self.downloadLyrics.emit(int(track_id))
        elif chosen == act_instr:
            self.markInstrumental.emit(selected_ids)
        elif chosen == act_uninstr:
            self.unmarkInstrumental.emit(selected_ids)

    def set_now_playing(self, track_id: int | None):
        if track_id is None:
            self.table.clearSelection()
            return

        row = self.model.row_for_track_id(track_id)
        if row < 0:
            return  # track not in current filtered view

        idx = self.proxy_model.mapFromSource(self.model.index(row, 0))
        if not idx.isValid():
            return
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
        return self.model.track_id_at(self._source_row(idx))

    def setArtistFilter(self, artist_id: int | None):
        self._artist_id = artist_id
        if self._active:
            self.refresh()

    def setAlbumFilter(self, album_id: int | None):
        self._album_id = album_id
        if self._active:
            self.refresh()

    def selected_track_ids(self) -> list[int]:
        sm = self.table.selectionModel()
        if sm is None or not sm.hasSelection():
            return []
        ids: list[int] = []
        for idx in sm.selectedRows():
            tid = self.model.track_id_at(self._source_row(idx))
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
                idx = self.proxy_model.mapFromSource(self.model.index(row, 0))
                if not idx.isValid():
                    continue
                sm.select(idx, QItemSelectionModel.Select | QItemSelectionModel.Rows)
                if first_idx is None:
                    first_idx = idx

        if first_idx is not None:
            sm.setCurrentIndex(first_idx, QItemSelectionModel.Current | QItemSelectionModel.Rows)
            self.table.scrollTo(first_idx, QTableView.ScrollHint.PositionAtCenter)

    def _apply_styles(self):
        self.setStyleSheet(load_stylesheet("data_table.qss", table_name="TrackTable"))

    def _source_row(self, index) -> int:
        return self.proxy_model.mapToSource(index).row()
