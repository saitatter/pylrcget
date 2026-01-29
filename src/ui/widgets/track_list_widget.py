# ui/track_list_widget.py
from __future__ import annotations

from PySide6.QtCore import Signal, Qt, QItemSelectionModel
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QMenu

from ui.models.track_table_model import TrackTableModel
from ui.delegates.actions_delegate import ActionsDelegate
from core.tracklist_models import TrackListRow
from db.database import get_track_rows


class TrackListWidget(QWidget):
    playTrack = Signal(int)       # track_id
    downloadLyrics = Signal(int)  # track_id

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

        self.table = QTableView()
        self.model = TrackTableModel([])
        self.table.setModel(self.model)

        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)

        self.table.setColumnWidth(0, 520)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 140)
        self.table.horizontalHeader().setStretchLastSection(True)
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
        row = idxs[0].row()
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
        row = index.row()
        track_id = self.model.track_id_at(row)
        if track_id is not None:
            self.playTrack.emit(int(track_id))

    def _on_context_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return

        row = idx.row()
        track_id = self.model.track_id_at(row)
        if track_id is None:
            return
        track_id = int(track_id)

        menu = QMenu(self)
        act_play = menu.addAction("Play")
        act_dl = menu.addAction("Download lyrics")

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == act_play:
            self.playTrack.emit(track_id)
        elif chosen == act_dl:
            self.downloadLyrics.emit(track_id)

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

    def _apply_styles(self):
        self.setStyleSheet("""
        QTableView#TrackTable {
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