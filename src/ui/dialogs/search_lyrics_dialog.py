from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from lrclib import LrcLibAPI

logger = logging.getLogger(__name__)


class _SearchWorker(QThread):
    finished = Signal(list, str)  # results, error

    def __init__(self, query: str, artist: str, title: str, album: str, lrclib_instance: str, parent=None):
        super().__init__(parent)
        self.query = query
        self.artist = artist
        self.title = title
        self.album = album
        self.lrclib_instance = lrclib_instance

    def run(self):
        try:
            api = LrcLibAPI(user_agent="pylrcget", base_url=self.lrclib_instance)
            results = api.search_lyrics(
                query=self.query or None,
                track_name=self.title or None,
                artist_name=self.artist or None,
                album_name=self.album or None,
            )
            self.finished.emit(list(results), "")
        except Exception as exc:
            logger.warning("LRCLIB search failed: %s", exc)
            self.finished.emit([], str(exc))


class SearchLyricsDialog(QDialog):
    """Dialog for searching LRCLIB and picking a lyrics result."""

    lyricsSelected = Signal(str, str)  # plain_lyrics, synced_lyrics

    def __init__(
        self,
        lrclib_instance: str,
        *,
        initial_query: str = "",
        initial_artist: str = "",
        initial_title: str = "",
        initial_album: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Search LRCLIB")
        self.resize(750, 500)
        self.lrclib_instance = lrclib_instance
        self._results: list = []
        self._worker: Optional[_SearchWorker] = None

        layout = QVBoxLayout(self)

        # Free-text query row
        query_row = QHBoxLayout()
        query_row.addWidget(QLabel("Query:"))
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("Free-text search (optional if fields below are filled)")
        self.query_edit.setText(initial_query)
        query_row.addWidget(self.query_edit, 1)
        layout.addLayout(query_row)

        # Structured fields row
        fields_row = QHBoxLayout()
        fields_row.addWidget(QLabel("Artist:"))
        self.artist_edit = QLineEdit()
        self.artist_edit.setPlaceholderText("Artist name")
        self.artist_edit.setText(initial_artist)
        fields_row.addWidget(self.artist_edit, 1)

        fields_row.addWidget(QLabel("Title:"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Track title")
        self.title_edit.setText(initial_title)
        fields_row.addWidget(self.title_edit, 1)

        fields_row.addWidget(QLabel("Album:"))
        self.album_edit = QLineEdit()
        self.album_edit.setPlaceholderText("Album name")
        self.album_edit.setText(initial_album)
        fields_row.addWidget(self.album_edit, 1)

        self.search_btn = QPushButton("Search")
        fields_row.addWidget(self.search_btn)
        layout.addLayout(fields_row)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Artist", "Title", "Album", "Duration", "Type"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.use_btn = QPushButton("Use Selected Lyrics")
        self.use_btn.setEnabled(False)
        self.cancel_btn = QPushButton("Cancel")
        btn_row.addWidget(self.use_btn)
        btn_row.addWidget(self.cancel_btn)
        layout.addLayout(btn_row)

        self.search_btn.clicked.connect(self._do_search)
        self.query_edit.returnPressed.connect(self._do_search)
        self.artist_edit.returnPressed.connect(self._do_search)
        self.title_edit.returnPressed.connect(self._do_search)
        self.album_edit.returnPressed.connect(self._do_search)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.table.doubleClicked.connect(self._on_double_click)
        self.use_btn.clicked.connect(self._use_selected)
        self.cancel_btn.clicked.connect(self.reject)

        if initial_query.strip():
            self._do_search()

    def _do_search(self):
        query = self.query_edit.text().strip()
        artist = self.artist_edit.text().strip()
        title = self.title_edit.text().strip()
        album = self.album_edit.text().strip()
        if not query and not artist and not title and not album:
            self.status_label.setText("Enter a search query or fill in at least one field.")
            return

        self.search_btn.setEnabled(False)
        self.status_label.setText("Searching...")
        self.table.setRowCount(0)
        self._results.clear()

        self._worker = _SearchWorker(query, artist, title, album, self.lrclib_instance, self)
        self._worker.finished.connect(self._on_search_finished)
        self._worker.start()

    def _on_search_finished(self, results: list, error: str):
        self.search_btn.setEnabled(True)
        self._worker = None

        if error:
            self.status_label.setText(f"Search failed: {error}")
            return

        self._results = results
        if not results:
            self.status_label.setText("No results found.")
            return

        self.status_label.setText(f"{len(results)} result(s) found.")
        self.table.setRowCount(len(results))
        for row, r in enumerate(results):
            self.table.setItem(row, 0, QTableWidgetItem(r.artist_name or ""))
            self.table.setItem(row, 1, QTableWidgetItem(r.track_name or ""))
            self.table.setItem(row, 2, QTableWidgetItem(r.album_name or ""))
            minutes, seconds = divmod(int(r.duration or 0), 60)
            self.table.setItem(row, 3, QTableWidgetItem(f"{minutes}:{seconds:02d}"))
            if r.instrumental:
                kind = "Instrumental"
            elif r.synced_lyrics:
                kind = "Synced"
            elif r.plain_lyrics:
                kind = "Plain"
            else:
                kind = "—"
            self.table.setItem(row, 4, QTableWidgetItem(kind))

    def _on_selection_changed(self):
        has_selection = bool(self.table.selectionModel().selectedRows())
        self.use_btn.setEnabled(has_selection)

    def _on_double_click(self):
        self._use_selected()

    def _use_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        idx = rows[0].row()
        if idx < 0 or idx >= len(self._results):
            return
        r = self._results[idx]
        self.lyricsSelected.emit(r.plain_lyrics or "", r.synced_lyrics or "")
        self.accept()
