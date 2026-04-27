from __future__ import annotations

import json
import logging
from typing import Optional

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.lrclib_client import LrcLibAPI

from ui.dialogs.publish_lyrics_dialog import PublishProgress, PublishWorker
from ui.spacing import SPACE_2, SPACE_3, SPACE_4, set_layout_spacing

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

class _SearchWorker(QThread):
    finished = Signal(list, str)

    def __init__(self, query: str, artist: str, title: str, album: str, lrclib_instance: str, parent=None):
        super().__init__(parent)
        self.query = query
        self.artist = artist
        self.title = title
        self.album = album
        self.lrclib_instance = lrclib_instance

    def run(self):
        try:
            api = LrcLibAPI(self.lrclib_instance)
            results = api.search_lyrics(
                query=self.query or None,
                track_name=self.title or None,
                artist_name=self.artist or None,
                album_name=self.album or None,
            )
            self.finished.emit(list(results), "")
        except Exception as exc:
            logger.warning("LRCLIB browser search failed: %s", exc)
            self.finished.emit([], str(exc))


# ---------------------------------------------------------------------------
# Publish Dialog (standalone, not subclassing PublishLyricsDialog)
# ---------------------------------------------------------------------------

class _BrowserPublishDialog(QDialog):
    """Publish lyrics for any song — not tied to a library track."""

    def __init__(self, lrclib_instance: str, selected_result=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Publish Lyrics to LRCLIB")
        self.setModal(True)
        self.resize(700, 550)
        self._lrclib_instance = lrclib_instance
        self._is_publishing = False

        root = QVBoxLayout(self)
        set_layout_spacing(root, margins=SPACE_4, spacing=SPACE_3)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        # --- Page 0: form ---
        form_page = QWidget()
        form_layout = QFormLayout(form_page)

        self._pub_artist = QLineEdit()
        self._pub_artist.setPlaceholderText("Artist name (required)")
        form_layout.addRow("Artist:", self._pub_artist)

        self._pub_title = QLineEdit()
        self._pub_title.setPlaceholderText("Track title (required)")
        form_layout.addRow("Title:", self._pub_title)

        self._pub_album = QLineEdit()
        self._pub_album.setPlaceholderText("Album name (required)")
        form_layout.addRow("Album:", self._pub_album)

        self._pub_duration = QSpinBox()
        self._pub_duration.setRange(1, 99999)
        self._pub_duration.setSuffix(" seconds")
        self._pub_duration.setValue(180)
        form_layout.addRow("Duration:", self._pub_duration)

        self._pub_synced = QTextEdit()
        self._pub_synced.setAcceptRichText(False)
        self._pub_synced.setPlaceholderText("[00:00.00] Paste synced lyrics here...")
        form_layout.addRow("Synced lyrics:", self._pub_synced)

        self._pub_plain = QTextEdit()
        self._pub_plain.setAcceptRichText(False)
        self._pub_plain.setPlaceholderText("Paste plain lyrics here...")
        form_layout.addRow("Plain lyrics:", self._pub_plain)

        self.stack.addWidget(form_page)

        # Pre-fill from selected result
        if selected_result is not None:
            r = selected_result
            self._pub_artist.setText(r.artist_name or "")
            self._pub_title.setText(r.track_name or "")
            self._pub_album.setText(r.album_name or "")
            self._pub_duration.setValue(int(r.duration or 180))
            self._pub_synced.setPlainText(r.synced_lyrics or "")
            self._pub_plain.setPlainText(r.plain_lyrics or "")

        # --- Page 1: progress ---
        progress_page = QWidget()
        progress_layout = QVBoxLayout(progress_page)
        set_layout_spacing(progress_layout, spacing=SPACE_3)
        progress_layout.setAlignment(Qt.AlignTop)

        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        progress_layout.addWidget(self.info_label)

        self.progress_table = QTableWidget(3, 2)
        self.progress_table.setHorizontalHeaderLabels(["Step", "Status"])
        self.progress_table.verticalHeader().setVisible(False)
        self.progress_table.horizontalHeader().setStretchLastSection(True)
        self.progress_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.progress_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.progress_table.setItem(0, 0, QTableWidgetItem("Request challenge..."))
        self.progress_table.setItem(1, 0, QTableWidgetItem("Solve challenge..."))
        self.progress_table.setItem(2, 0, QTableWidgetItem("Publish lyrics..."))
        self._set_progress(PublishProgress())
        progress_layout.addWidget(self.progress_table)

        self.stack.addWidget(progress_page)

        # --- Footer ---
        footer = QHBoxLayout()
        set_layout_spacing(footer, spacing=SPACE_2)
        footer.addStretch(1)

        self.btn_primary = QPushButton("Publish")
        self.btn_secondary = QPushButton("Cancel")
        self.btn_primary.clicked.connect(self._on_primary)
        self.btn_secondary.clicked.connect(self._on_secondary)
        footer.addWidget(self.btn_primary)
        footer.addWidget(self.btn_secondary)
        root.addLayout(footer)

        self.stack.setCurrentIndex(0)

    def _set_progress(self, prog: PublishProgress):
        self.progress_table.setItem(0, 1, QTableWidgetItem(prog.requestChallenge))
        self.progress_table.setItem(1, 1, QTableWidgetItem(prog.solveChallenge))
        self.progress_table.setItem(2, 1, QTableWidgetItem(prog.publishLyrics))

    def _on_primary(self):
        if self.stack.currentIndex() == 0:
            artist = self._pub_artist.text().strip()
            title = self._pub_title.text().strip()
            album = self._pub_album.text().strip()
            duration = self._pub_duration.value()

            if not artist or not title or not album:
                QMessageBox.warning(self, "Missing Fields", "Artist, title, and album are required.")
                return

            synced = self._pub_synced.toPlainText().strip() or None
            plain = self._pub_plain.toPlainText().strip() or None

            if not synced and not plain:
                QMessageBox.warning(self, "No Lyrics", "Provide synced or plain lyrics to publish.")
                return

            from ui.dialogs.publish_lyrics_dialog import lint_lyrics
            for text, is_synced in [(synced, True), (plain, False)]:
                if not text:
                    continue
                problems = lint_lyrics(text, is_synced=is_synced)
                errors = [p for p in problems if p.severity == "error"]
                if errors:
                    msg = "\n".join(f"Line {p.line}: {p.message}" for p in errors)
                    QMessageBox.warning(self, "Lyrics Issues", msg)
                    return

            self._payload = {
                "title": title,
                "artistName": artist,
                "albumName": album,
                "duration": float(duration),
                "plainLyrics": plain,
                "syncedLyrics": synced,
            }
            self.stack.setCurrentIndex(1)
            self.info_label.setText(
                f"Publishing lyrics for <b>{title} — {artist}</b>..."
            )
            self._start_publish()
            return

        # On progress page after failure — retry
        if not self._is_publishing:
            self._start_publish()

    def _on_secondary(self):
        if not self._is_publishing:
            self.reject()

    def _start_publish(self):
        self._is_publishing = True
        self.btn_primary.setEnabled(False)
        self.btn_secondary.setEnabled(False)
        self.btn_primary.setText("Publishing...")
        self._set_progress(PublishProgress())

        self._worker = PublishWorker(self._payload, self._lrclib_instance, self)
        self._worker.progress.connect(self._set_progress)
        self._worker.finished.connect(self._publish_done)
        self._worker.start()

    def _publish_done(self, ok: bool, msg: str):
        self._is_publishing = False
        if ok:
            self.info_label.setText(f"<b>{msg}</b>")
            self.btn_primary.setText("Published")
            QTimer.singleShot(1000, self.accept)
            return
        self.info_label.setText(f"<b>Publishing failed.</b><br>{msg}")
        self.btn_primary.setText("Retry Publish")
        self.btn_primary.setEnabled(True)
        self.btn_secondary.setEnabled(True)


# ---------------------------------------------------------------------------
# Main Widget
# ---------------------------------------------------------------------------

_TYPE_COLORS = {
    "Synced": "#4CAF50",
    "Plain": "#2196F3",
    "Instrumental": "#9C27B0",
    "—": "#888888",
}


def _match_rank(r) -> int:
    if r.synced_lyrics:
        return 0
    if r.plain_lyrics:
        return 1
    if r.instrumental:
        return 2
    return 3


class LrclibBrowserWidget(QWidget):
    """Standalone LRCLIB browser tab — search, view, edit, publish any lyrics."""

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self._app_state = app_state
        self._results: list = []
        self._search_worker: Optional[_SearchWorker] = None
        self._selected_result = None
        self._lrclib_url = "https://lrclib.net/api"

        root = QVBoxLayout(self)
        set_layout_spacing(root, margins=SPACE_3, spacing=SPACE_2)

        # --- Search bar ---
        search_layout = QHBoxLayout()
        set_layout_spacing(search_layout, spacing=SPACE_2)

        search_layout.addWidget(QLabel("Query:"))
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("Free-text search")
        search_layout.addWidget(self.query_edit, 2)

        search_layout.addWidget(QLabel("Artist:"))
        self.artist_edit = QLineEdit()
        self.artist_edit.setPlaceholderText("Artist")
        search_layout.addWidget(self.artist_edit, 1)

        search_layout.addWidget(QLabel("Title:"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Title")
        search_layout.addWidget(self.title_edit, 1)

        search_layout.addWidget(QLabel("Album:"))
        self.album_edit = QLineEdit()
        self.album_edit.setPlaceholderText("Album")
        search_layout.addWidget(self.album_edit, 1)

        self.search_btn = QPushButton("Search")
        search_layout.addWidget(self.search_btn)
        root.addLayout(search_layout)

        self.status_label = QLabel("Search LRCLIB for any lyrics.")
        root.addWidget(self.status_label)

        # --- Splitter: results table | lyrics preview ---
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: results table
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
        self.splitter.addWidget(self.table)

        # Right: preview panel
        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        set_layout_spacing(preview_layout, margins=0, spacing=SPACE_2)

        self.preview_header = QLabel("Select a result to preview lyrics")
        self.preview_header.setWordWrap(True)
        font = self.preview_header.font()
        font.setWeight(QFont.Weight.Bold)
        self.preview_header.setFont(font)
        preview_layout.addWidget(self.preview_header)

        self.preview_tabs = QTabWidget()
        self.synced_preview = QPlainTextEdit()
        self.synced_preview.setReadOnly(True)
        self.synced_preview.setPlaceholderText("No synced lyrics")
        self.plain_preview = QPlainTextEdit()
        self.plain_preview.setReadOnly(True)
        self.plain_preview.setPlaceholderText("No plain lyrics")
        self.preview_tabs.addTab(self.synced_preview, "Synced")
        self.preview_tabs.addTab(self.plain_preview, "Plain")
        preview_layout.addWidget(self.preview_tabs, 1)

        # Action buttons
        actions_row = QHBoxLayout()
        set_layout_spacing(actions_row, spacing=SPACE_2)

        self.copy_synced_btn = QPushButton("Copy Synced")
        self.copy_plain_btn = QPushButton("Copy Plain")
        self.publish_btn = QPushButton("Publish New Lyrics")
        self.copy_synced_btn.setEnabled(False)
        self.copy_plain_btn.setEnabled(False)

        actions_row.addWidget(self.copy_synced_btn)
        actions_row.addWidget(self.copy_plain_btn)
        actions_row.addStretch(1)
        actions_row.addWidget(self.publish_btn)
        preview_layout.addLayout(actions_row)

        self.splitter.addWidget(preview_panel)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        root.addWidget(self.splitter, 1)

        # --- Connections ---
        self.search_btn.clicked.connect(self._do_search)
        self.query_edit.returnPressed.connect(self._do_search)
        self.artist_edit.returnPressed.connect(self._do_search)
        self.title_edit.returnPressed.connect(self._do_search)
        self.album_edit.returnPressed.connect(self._do_search)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.copy_synced_btn.clicked.connect(self._copy_synced)
        self.copy_plain_btn.clicked.connect(self._copy_plain)
        self.publish_btn.clicked.connect(self._open_publish)

    def set_lrclib_url(self, url: str) -> None:
        self._lrclib_url = url

    # --- Search ---

    def _do_search(self):
        query = self.query_edit.text().strip()
        artist = self.artist_edit.text().strip()
        title = self.title_edit.text().strip()
        album = self.album_edit.text().strip()
        if not query and not artist and not title and not album:
            self.status_label.setText("Enter a search query or fill in at least one field.")
            return

        self.search_btn.setEnabled(False)
        self.status_label.setText("Searching LRCLIB...")
        self.table.setRowCount(0)
        self._results.clear()
        self._clear_preview()

        self._search_worker = _SearchWorker(query, artist, title, album, self._lrclib_url, self)
        self._search_worker.finished.connect(self._on_search_finished)
        self._search_worker.start()

    def _on_search_finished(self, results: list, error: str):
        self.search_btn.setEnabled(True)
        self._search_worker = None

        if error:
            self.status_label.setText(f"Search failed: {error}")
            return

        if not results:
            self._results = []
            self.status_label.setText("No results found.")
            return

        results.sort(key=_match_rank)
        self._results = results

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
            type_item = QTableWidgetItem(kind)
            type_item.setForeground(QColor(_TYPE_COLORS.get(kind, "#888888")))
            self.table.setItem(row, 4, type_item)

    # --- Preview ---

    def _on_selection_changed(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self._clear_preview()
            return

        idx = rows[0].row()
        if idx < 0 or idx >= len(self._results):
            self._clear_preview()
            return

        r = self._results[idx]
        self._selected_result = r
        artist = r.artist_name or ""
        title = r.track_name or ""
        album = r.album_name or ""
        minutes, seconds = divmod(int(r.duration or 0), 60)
        duration_str = f"{minutes}:{seconds:02d}"

        header_parts = []
        if artist:
            header_parts.append(artist)
        if title:
            header_parts.append(title)
        label = " — ".join(header_parts) or "Unknown"
        if album:
            label += f"  ({album})"
        label += f"  [{duration_str}]"

        if r.instrumental:
            label += "  \u266a Instrumental"

        self.preview_header.setText(label)

        synced = r.synced_lyrics or ""
        plain = r.plain_lyrics or ""
        self.synced_preview.setPlainText(synced)
        self.plain_preview.setPlainText(plain)

        self.copy_synced_btn.setEnabled(bool(synced.strip()))
        self.copy_plain_btn.setEnabled(bool(plain.strip()))

        # Show the tab that has content
        if synced.strip():
            self.preview_tabs.setCurrentIndex(0)
        elif plain.strip():
            self.preview_tabs.setCurrentIndex(1)

    def _clear_preview(self):
        self._selected_result = None
        self.preview_header.setText("Select a result to preview lyrics")
        self.synced_preview.clear()
        self.plain_preview.clear()
        self.copy_synced_btn.setEnabled(False)
        self.copy_plain_btn.setEnabled(False)

    # --- Copy ---

    def _copy_synced(self):
        from PySide6.QtWidgets import QApplication
        text = self.synced_preview.toPlainText()
        if text.strip():
            QApplication.clipboard().setText(text)
            self.status_label.setText("Synced lyrics copied to clipboard.")

    def _copy_plain(self):
        from PySide6.QtWidgets import QApplication
        text = self.plain_preview.toPlainText()
        if text.strip():
            QApplication.clipboard().setText(text)
            self.status_label.setText("Plain lyrics copied to clipboard.")

    # --- Publish ---

    def _open_publish(self):
        dlg = _BrowserPublishDialog(
            lrclib_instance=self._lrclib_url,
            selected_result=self._selected_result,
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.status_label.setText("Lyrics published successfully.")
