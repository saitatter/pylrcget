# ui/lyrics_view.py
from __future__ import annotations

import re
from bisect import bisect_right
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QStackedWidget,
    QTextEdit, QTableWidget, QTableWidgetItem,
    QPushButton, QHBoxLayout, QMessageBox
)

_TS_RE = re.compile(r"\[(\d+):(\d+)(?:\.(\d+))?\]")


def _ts_to_ms(mm: str, ss: str, frac: str | None) -> int:
    m = int(mm)
    s = int(ss)
    if frac is None:
        ms = 0
    else:
        frac = frac.strip()
        if len(frac) == 1:
            ms = int(frac) * 100
        elif len(frac) == 2:
            ms = int(frac) * 10
        else:
            ms = int(frac[:3])
    return (m * 60 + s) * 1000 + ms


def _ms_to_ts(ms: int) -> str:
    """Format milliseconds as mm:ss.xx (centiseconds)."""
    if ms < 0:
        ms = 0
    total_s = ms // 1000
    m = total_s // 60
    s = total_s % 60
    cs = (ms % 1000) // 10
    return f"{m:02d}:{s:02d}.{cs:02d}"


def _parse_ts_str(ts: str) -> Optional[int]:
    """
    Accepts:
      - mm:ss
      - mm:ss.xx
      - mm:ss.xxx
    """
    t = (ts or "").strip()
    if not t:
        return None

    # normalize comma to dot
    t = t.replace(",", ".")

    # mm:ss(.frac)
    m = re.match(r"^(\d+):(\d{1,2})(?:\.(\d{1,3}))?$", t)
    if not m:
        return None

    mm = m.group(1)
    ss = m.group(2)
    frac = m.group(3)

    # reuse _ts_to_ms frac logic: but it expects strings
    try:
        return _ts_to_ms(mm, ss, frac)
    except Exception:
        return None


def parse_lrc(lrc_text: str) -> List[Tuple[int, str]]:
    """
    Returns list of (time_ms, text) sorted by time.
    Supports multiple timestamps per line.
    Ignores metadata tags like [ar:], [ti:], etc.
    """
    out: List[Tuple[int, str]] = []
    if not lrc_text:
        return out

    for raw_line in lrc_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # ignore metadata
        if line.startswith("[ar:") or line.startswith("[ti:") or line.startswith("[al:") or line.startswith("[by:") or line.startswith("[offset:") or line.startswith("[au:"):
            continue

        matches = list(_TS_RE.finditer(line))
        if not matches:
            continue

        text = _TS_RE.sub("", line).strip()
        if not text:
            continue

        for m in matches:
            t = _ts_to_ms(m.group(1), m.group(2), m.group(3))
            out.append((t, text))

    out.sort(key=lambda x: x[0])
    return out


class LyricsView(QWidget):
    """
    Right-side lyrics panel:
      - Synced editor: table (Time | Text), editable
      - Plain editor: QTextEdit
      - None/instrumental: message

    Features:
      - click row -> seek
      - snap selected row time to current playback time
      - highlight current row while playing
      - add/delete row
      - save -> emits (lrc_text, plain_text)
    """
    seekRequested = Signal(int)          # ms
    publishSyncedRequested = Signal()
    publishPlainRequested = Signal()
    saveRequested = Signal(str, str)     # lrc_text, plain_text

    def __init__(self, parent=None):
        super().__init__(parent)

        self._current_pos_ms: int = 0
        self._times: List[int] = []
        self._current_index: int = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # --- header ---
        header = QHBoxLayout()
        header.setSpacing(8)

        self.title = QLabel("Lyrics")
        self.title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.title.setStyleSheet("font-weight: 650; font-size: 14px;")
        header.addWidget(self.title, 1)

        self.btn_snap = QPushButton("Snap")
        self.btn_add = QPushButton("+ Line")
        self.btn_del = QPushButton("Delete")
        self.btn_save = QPushButton("Save")

        self.btn_snap.setEnabled(False)
        self.btn_add.setEnabled(False)
        self.btn_del.setEnabled(False)
        self.btn_save.setEnabled(False)

        self.btn_snap.clicked.connect(self._snap_selected_line_to_current_time)
        self.btn_add.clicked.connect(self._add_line_after_selection)
        self.btn_del.clicked.connect(self._delete_selected_line)
        self.btn_save.clicked.connect(self._emit_save)

        header.addWidget(self.btn_snap)
        header.addWidget(self.btn_add)
        header.addWidget(self.btn_del)
        header.addWidget(self.btn_save)

        self.btn_publish_synced = QPushButton("Publish Synced")
        self.btn_publish_plain = QPushButton("Publish Plain")
        self.btn_publish_synced.setEnabled(False)
        self.btn_publish_plain.setEnabled(False)
        self.btn_publish_synced.clicked.connect(lambda: self.publishSyncedRequested.emit())
        self.btn_publish_plain.clicked.connect(lambda: self.publishPlainRequested.emit())

        header.addWidget(self.btn_publish_synced)
        header.addWidget(self.btn_publish_plain)

        root.addLayout(header)

        # --- stack: msg / plain / synced ---
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self.msg = QLabel("No lyrics")
        self.msg.setAlignment(Qt.AlignCenter)
        self.msg.setWordWrap(True)
        self.msg.setStyleSheet("opacity: 0.75;")
        self.stack.addWidget(self.msg)

        # Plain editor (editable if you want)
        self.plain = QTextEdit()
        self.plain.setPlaceholderText("No lyrics")
        self.plain.textChanged.connect(self._on_any_edit)
        self.stack.addWidget(self.plain)

        # Synced editor table
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Time", "Text"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(self.table.SelectionMode.SingleSelection)
        self.table.setEditTriggers(self.table.EditTrigger.DoubleClicked | self.table.EditTrigger.EditKeyPressed)
        self.table.cellClicked.connect(self._on_table_clicked_seek)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table.itemChanged.connect(self._on_table_item_changed)

        self.table.setColumnWidth(0, 95)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.stack.addWidget(self.table)

        self.show_none("No track selected")

    # --- public API ---
    def on_player_position(self, ms: int):
        self._current_pos_ms = int(ms)

        # only highlight in synced view
        if self.stack.currentWidget() is not self.table:
            return
        if not self._times:
            return

        pos = self._current_pos_ms
        idx = bisect_right(self._times, pos) - 1
        if idx < 0:
            idx = 0
        if idx == self._current_index:
            return

        self._current_index = idx

        # highlight row without breaking editing too aggressively
        self.table.blockSignals(True)
        self.table.selectRow(idx)
        self.table.blockSignals(False)

        self.table.scrollToItem(self.table.item(idx, 1), self.table.ScrollHint.PositionAtCenter)

    def show_none(self, message: str):
        self._reset_state()
        self.msg.setText(message)
        self.stack.setCurrentWidget(self.msg)

    def set_track_lyrics(self, title: str, txt_lyrics: Optional[str], lrc_lyrics: Optional[str], instrumental: bool):
        self.title.setText(title or "Lyrics")

        if instrumental:
            self._reset_state()
            self.msg.setText("Instrumental")
            self.stack.setCurrentWidget(self.msg)
            return

        lrc = (lrc_lyrics or "").strip()
        txt = (txt_lyrics or "").strip()

        self.btn_publish_synced.setEnabled(bool(lrc))
        self.btn_publish_plain.setEnabled(bool(txt))

        # Prefer showing synced editor if we have LRC that parses
        if lrc:
            pairs = parse_lrc(lrc)
            if pairs:
                self._set_synced(pairs)
                # still keep plain editor content synced
                if txt:
                    self.plain.blockSignals(True)
                    self.plain.setPlainText(txt)
                    self.plain.blockSignals(False)
                else:
                    # derive plain from table text (not timestamps)
                    self.plain.blockSignals(True)
                    self.plain.setPlainText("\n".join([t for _, t in pairs]))
                    self.plain.blockSignals(False)
                return

        # else fall back to plain
        if txt:
            self._set_plain(txt)
        else:
            self.show_none("No lyrics")

    # --- internal helpers ---
    def _reset_state(self):
        self._times = []
        self._current_index = -1
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.blockSignals(False)
        self.btn_snap.setEnabled(False)
        self.btn_add.setEnabled(False)
        self.btn_del.setEnabled(False)
        self.btn_save.setEnabled(False)

    def _set_plain(self, txt: str):
        self._reset_state()
        self.plain.blockSignals(True)
        self.plain.setPlainText(txt)
        self.plain.blockSignals(False)
        self.stack.setCurrentWidget(self.plain)

        # plain editing
        self.btn_save.setEnabled(True)
        self.btn_add.setEnabled(False)
        self.btn_del.setEnabled(False)
        self.btn_snap.setEnabled(False)

    def _set_synced(self, pairs: List[Tuple[int, str]]):
        self._reset_state()
        self.stack.setCurrentWidget(self.table)

        self.table.blockSignals(True)
        self.table.setRowCount(len(pairs))
        self._times = []

        for row, (ms, text) in enumerate(pairs):
            self._times.append(int(ms))

            it_time = QTableWidgetItem(_ms_to_ts(int(ms)))
            it_time.setData(Qt.ItemDataRole.UserRole, int(ms))  # store ms raw
            it_time.setFlags(it_time.flags() | Qt.ItemIsEditable)

            it_text = QTableWidgetItem(text)
            it_text.setFlags(it_text.flags() | Qt.ItemIsEditable)

            self.table.setItem(row, 0, it_time)
            self.table.setItem(row, 1, it_text)

        self.table.blockSignals(False)

        # enable editing controls
        self.btn_add.setEnabled(True)
        self.btn_del.setEnabled(self.table.currentRow() >= 0)
        self.btn_snap.setEnabled(self.table.currentRow() >= 0)
        self.btn_save.setEnabled(True)

    def _rebuild_times_cache(self):
        times: List[int] = []
        for r in range(self.table.rowCount()):
            it_time = self.table.item(r, 0)
            ms = int(it_time.data(Qt.ItemDataRole.UserRole) or 0) if it_time else 0
            times.append(ms)
        self._times = times

    def _on_any_edit(self):
        # Any edit in plain view keeps save enabled
        if self.stack.currentWidget() is self.plain:
            self.btn_save.setEnabled(True)

    def _on_table_selection_changed(self):
        row = self.table.currentRow()
        has = row >= 0
        self.btn_del.setEnabled(has)
        self.btn_snap.setEnabled(has)

    def _on_table_clicked_seek(self, row: int, col: int):
        it_time = self.table.item(row, 0)
        if not it_time:
            return
        ms = it_time.data(Qt.ItemDataRole.UserRole)
        if ms is None:
            return
        self.seekRequested.emit(int(ms))

    def _on_table_item_changed(self, item: QTableWidgetItem):
        # If user edited the Time cell, validate and update ms
        if item.column() != 0:
            return

        new_ms = _parse_ts_str(item.text())
        if new_ms is None:
            # revert to stored ms
            old_ms = int(item.data(Qt.ItemDataRole.UserRole) or 0)
            item.setText(_ms_to_ts(old_ms))
            return

        item.setData(Qt.ItemDataRole.UserRole, int(new_ms))
        item.setText(_ms_to_ts(int(new_ms)))  # normalize format
        self._rebuild_times_cache()

    def _add_line_after_selection(self):
        row = self.table.currentRow()
        insert_at = row + 1 if row >= 0 else self.table.rowCount()

        # default time: current playback time
        ms = int(self._current_pos_ms)

        self.table.blockSignals(True)
        self.table.insertRow(insert_at)

        it_time = QTableWidgetItem(_ms_to_ts(ms))
        it_time.setData(Qt.ItemDataRole.UserRole, ms)
        it_time.setFlags(it_time.flags() | Qt.ItemIsEditable)

        it_text = QTableWidgetItem("")
        it_text.setFlags(it_text.flags() | Qt.ItemIsEditable)

        self.table.setItem(insert_at, 0, it_time)
        self.table.setItem(insert_at, 1, it_text)
        self.table.blockSignals(False)

        self._rebuild_times_cache()
        self.table.selectRow(insert_at)
        self.table.setCurrentCell(insert_at, 1)
        self.table.editItem(self.table.item(insert_at, 1))

    def _delete_selected_line(self):
        row = self.table.currentRow()
        if row < 0:
            return
        self.table.blockSignals(True)
        self.table.removeRow(row)
        self.table.blockSignals(False)
        self._rebuild_times_cache()

    def _snap_selected_line_to_current_time(self):
        row = self.table.currentRow()
        if row < 0:
            return

        it_time = self.table.item(row, 0)
        if not it_time:
            return

        ms = int(self._current_pos_ms)
        self.table.blockSignals(True)
        it_time.setData(Qt.ItemDataRole.UserRole, ms)
        it_time.setText(_ms_to_ts(ms))
        self.table.blockSignals(False)

        self._rebuild_times_cache()

    def _emit_save(self):
        # Synced view: build LRC + plain
        if self.stack.currentWidget() is self.table:
            pairs: List[Tuple[int, str]] = []
            for r in range(self.table.rowCount()):
                it_time = self.table.item(r, 0)
                it_text = self.table.item(r, 1)
                ms = int(it_time.data(Qt.ItemDataRole.UserRole) or 0) if it_time else 0
                text = (it_text.text() if it_text else "").strip()
                if not text:
                    continue
                pairs.append((ms, text))

            # sort by time
            pairs.sort(key=lambda x: x[0])

            lrc_lines = [f"[{_ms_to_ts(ms)}] {text}" for ms, text in pairs]
            lrc = "\n".join(lrc_lines).strip()

            plain = "\n".join([text for _, text in pairs]).strip()

            self.saveRequested.emit(lrc, plain)
            return

        # Plain view: save plain only
        if self.stack.currentWidget() is self.plain:
            txt = (self.plain.toPlainText() or "").strip()
            self.saveRequested.emit("", txt)
            return
