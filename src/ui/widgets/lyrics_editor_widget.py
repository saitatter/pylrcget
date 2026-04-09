# ui/lyrics_view.py
from __future__ import annotations

import re
from bisect import bisect_right
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QStackedWidget,
    QTextEdit, QTableWidget, QTableWidgetItem,
    QPushButton, QHBoxLayout, QDoubleSpinBox
)

from ui.spacing import SPACE_2, SPACE_3, set_layout_spacing
from ui.style_loader import load_stylesheet
from ui.widgets.empty_state_widget import EmptyStateWidget

_TS_RE = re.compile(r"\[(\d+):(\d+)(?:\.(\d+))?\]")
TIMESTAMP_MS_ROLE = Qt.ItemDataRole.UserRole
TIMESTAMP_VALID_ROLE = Qt.ItemDataRole.UserRole + 1


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
        line = raw_line.rstrip("\n")
        # Keep truly empty raw lines only if you want blank rows with no timestamp.
        # For synced LRC, blank lines without timestamp can't be placed on a timeline, so we ignore them.
        if not line.strip():
            continue

        # ignore metadata
        if line.startswith("[ar:") or line.startswith("[ti:") or line.startswith("[al:") or line.startswith("[by:") or line.startswith("[offset:") or line.startswith("[au:"):
            continue

        matches = list(_TS_RE.finditer(line))
        if not matches:
            continue

        text = _TS_RE.sub("", line)
        # Keep empty lyrics lines (timestamp-only lines).
        # Don't .strip() here if you want to preserve intentional spaces; usually not needed.
        text = text.strip()

        for m in matches:
            t = _ts_to_ms(m.group(1), m.group(2), m.group(3))
            out.append((t, text))

    out.sort(key=lambda x: x[0])
    return out


class LyricsEditorWidget(QWidget):
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
    downloadRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._current_pos_ms: int = 0
        self._times: List[int] = []
        self._current_index: int = -1
        self._invalid_rows: set[int] = set()
        self._default_button_text: dict[QPushButton, str] = {}
        self._publish_synced_available = False
        self._publish_plain_available = False
        self._reaction_delay_ms: int = 0

        root = QVBoxLayout(self)
        set_layout_spacing(root, margins=SPACE_3, spacing=SPACE_2)

        # --- header ---
        header = QHBoxLayout()
        set_layout_spacing(header, spacing=SPACE_2)

        self.title = QLabel("Lyrics")
        self.title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.title.setObjectName("LyricsTitle")
        header.addWidget(self.title, 1)

        self.btn_snap = QPushButton("Snap")
        self.btn_shift_minus = QPushButton("-0.1s")
        self.btn_shift_plus = QPushButton("+0.1s")
        self.shift_spin = QDoubleSpinBox()
        self.shift_spin.setRange(-30.0, 30.0)
        self.shift_spin.setDecimals(2)
        self.shift_spin.setSingleStep(0.05)
        self.shift_spin.setValue(0.10)
        self.shift_spin.setSuffix(" s")
        self.btn_shift_selected = QPushButton("Shift Selected")
        self.btn_shift_all_from_first = QPushButton("Shift All from First")
        self.btn_add = QPushButton("+ Line")
        self.btn_del = QPushButton("Delete")
        self.btn_save = QPushButton("Save")

        self.btn_snap.setEnabled(False)
        self.btn_shift_minus.setEnabled(False)
        self.btn_shift_plus.setEnabled(False)
        self.shift_spin.setEnabled(False)
        self.btn_shift_selected.setEnabled(False)
        self.btn_shift_all_from_first.setEnabled(False)
        self.btn_add.setEnabled(False)
        self.btn_del.setEnabled(False)
        self.btn_save.setEnabled(False)

        self.btn_snap.clicked.connect(self._snap_selected_line_to_current_time)
        self.btn_shift_minus.clicked.connect(lambda: self._shift_selected_lines(-100))
        self.btn_shift_plus.clicked.connect(lambda: self._shift_selected_lines(100))
        self.btn_shift_selected.clicked.connect(self._shift_selected_lines_by_custom_amount)
        self.btn_shift_all_from_first.clicked.connect(self._shift_all_lines_from_first_delta)
        self.btn_add.clicked.connect(self._add_line_after_selection)
        self.btn_del.clicked.connect(self._delete_selected_line)
        self.btn_save.clicked.connect(self._emit_save)

        header.addWidget(self.btn_snap)
        header.addWidget(self.btn_shift_minus)
        header.addWidget(self.btn_shift_plus)
        header.addWidget(self.shift_spin)
        header.addWidget(self.btn_shift_selected)
        header.addWidget(self.btn_shift_all_from_first)
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

        self.validation_hint = QLabel("")
        self.validation_hint.setObjectName("LyricsValidationHint")
        self.validation_hint.hide()
        root.addWidget(self.validation_hint)

        # --- stack: msg / plain / synced ---
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self.empty_state = EmptyStateWidget()
        self.empty_state.actionTriggered.connect(self.downloadRequested.emit)
        self.stack.addWidget(self.empty_state)

        # Plain editor (editable if you want)
        self.plain = QTextEdit()
        self.plain.setPlaceholderText("Lyrics will appear here")
        self.plain.textChanged.connect(self._on_any_edit)
        self.stack.addWidget(self.plain)

        # Synced editor table
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Time", "Text"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(self.table.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(self.table.EditTrigger.DoubleClicked | self.table.EditTrigger.EditKeyPressed)
        self.table.cellClicked.connect(self._on_table_clicked_seek)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table.itemChanged.connect(self._on_table_item_changed)

        self.table.setColumnWidth(0, 95)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.stack.addWidget(self.table)

        self._default_button_text = {
            self.btn_save: "Save",
            self.btn_publish_synced: "Publish Synced",
            self.btn_publish_plain: "Publish Plain",
        }

        self._apply_styles()
        self.show_none("Choose a track to review or edit its lyrics.")

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

        self._refresh_row_styles()

        self.table.scrollToItem(self.table.item(idx, 1), self.table.ScrollHint.PositionAtCenter)

    def set_reaction_delay_ms(self, reaction_delay_ms: int) -> None:
        self._reaction_delay_ms = int(reaction_delay_ms or 0)

    def _apply_styles(self):
        self.setStyleSheet(load_stylesheet("lyrics_editor.qss"))
        if hasattr(self, "empty_state") and self.empty_state:
            self.empty_state._apply_styles()

    def show_none(self, message: str):
        self._reset_state()
        self.empty_state.configure(
            icon_name="audio-lines.svg",
            title="No track selected",
            body=message,
            action_text=None,
        )
        self.stack.setCurrentWidget(self.empty_state)

    def set_track_lyrics(self, title: str, txt_lyrics: Optional[str], lrc_lyrics: Optional[str], instrumental: bool):
        self.title.setText(title or "Lyrics")

        if instrumental:
            self._reset_state()
            self.empty_state.configure(
                icon_name="audio-lines.svg",
                title="Instrumental track",
                body="This track is marked as instrumental, so there are no lyrics to edit or publish.",
                action_text=None,
            )
            self.stack.setCurrentWidget(self.empty_state)
            return

        lrc = (lrc_lyrics or "").strip()
        txt = (txt_lyrics or "").strip()

        self._publish_synced_available = bool(lrc)
        self._publish_plain_available = bool(txt)
        self.btn_publish_synced.setEnabled(self._publish_synced_available)
        self.btn_publish_plain.setEnabled(self._publish_plain_available)

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
                    self.plain.setPlainText("\n".join([t.rstrip() for _, t in pairs]).rstrip())
                    self.plain.blockSignals(False)
                return

        # else fall back to plain
        if txt:
            self._set_plain(txt)
        else:
            self._reset_state()
            self.empty_state.configure(
                icon_name="audio-lines.svg",
                title="No lyrics available yet",
                body="Download lyrics from LRCLIB to start editing, or leave this track lyric-free.",
                action_text="Download Lyrics",
            )
            self.stack.setCurrentWidget(self.empty_state)

    # --- internal helpers ---
    def _reset_state(self):
        self._times = []
        self._current_index = -1
        self._publish_synced_available = False
        self._publish_plain_available = False
        self._invalid_rows.clear()
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.blockSignals(False)
        self._set_validation_message("")
        self.btn_snap.setEnabled(False)
        self.btn_shift_minus.setEnabled(False)
        self.btn_shift_plus.setEnabled(False)
        self.shift_spin.setEnabled(False)
        self.btn_shift_selected.setEnabled(False)
        self.btn_shift_all_from_first.setEnabled(False)
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
        self.btn_shift_minus.setEnabled(False)
        self.btn_shift_plus.setEnabled(False)
        self.shift_spin.setEnabled(False)
        self.btn_shift_selected.setEnabled(False)
        self.btn_shift_all_from_first.setEnabled(False)

    def _set_synced(self, pairs: List[Tuple[int, str]]):
        self._reset_state()
        self.stack.setCurrentWidget(self.table)

        self.table.blockSignals(True)
        self.table.setRowCount(len(pairs))
        self._times = []

        for row, (ms, text) in enumerate(pairs):
            self._times.append(int(ms))

            it_time = QTableWidgetItem(_ms_to_ts(int(ms)))
            it_time.setData(TIMESTAMP_MS_ROLE, int(ms))
            it_time.setData(TIMESTAMP_VALID_ROLE, True)
            it_time.setFlags(it_time.flags() | Qt.ItemIsEditable)

            it_text = QTableWidgetItem(text)
            it_text.setFlags(it_text.flags() | Qt.ItemIsEditable)

            self.table.setItem(row, 0, it_time)
            self.table.setItem(row, 1, it_text)

        self.table.blockSignals(False)
        self._refresh_row_styles()

        # enable editing controls
        self.btn_add.setEnabled(True)
        self.btn_shift_all_from_first.setEnabled(bool(self.table.rowCount()))
        has_selection = self.table.currentRow() >= 0
        self.btn_del.setEnabled(has_selection)
        self.btn_snap.setEnabled(has_selection)
        self.btn_shift_minus.setEnabled(has_selection)
        self.btn_shift_plus.setEnabled(has_selection)
        self.shift_spin.setEnabled(has_selection)
        self.btn_shift_selected.setEnabled(has_selection)
        self.btn_save.setEnabled(not self._invalid_rows)

    def _rebuild_times_cache(self):
        times: List[int] = []
        for r in range(self.table.rowCount()):
            it_time = self.table.item(r, 0)
            ms = int(it_time.data(TIMESTAMP_MS_ROLE) or 0) if it_time else 0
            times.append(ms)
        self._times = times

    def _refresh_row_styles(self):
        current_row = self._current_index if self.stack.currentWidget() is self.table else -1
        selected_row = self.table.currentRow()

        for row in range(self.table.rowCount()):
            is_current = row == current_row
            is_selected = row == selected_row
            is_invalid = row in self._invalid_rows

            bg = None
            fg = QColor("#e5e7eb")
            if is_invalid:
                bg = QColor("#3f1418")
                fg = QColor("#fecaca")
            elif is_current and is_selected:
                bg = QColor("#0b2942")
                fg = QColor("#e0f2fe")
            elif is_current:
                bg = QColor("#0f2235")
                fg = QColor("#bae6fd")
            elif is_selected:
                bg = QColor("#172554")
                fg = QColor("#dbeafe")

            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if not item:
                    continue
                if bg is None:
                    item.setBackground(Qt.GlobalColor.transparent)
                else:
                    item.setBackground(bg)
                item.setForeground(fg)

    def _update_save_enabled(self):
        if self.stack.currentWidget() is self.table:
            self.btn_save.setEnabled(not self._invalid_rows)
        elif self.stack.currentWidget() is self.plain:
            self.btn_save.setEnabled(True)
        else:
            self.btn_save.setEnabled(False)

    def _set_validation_message(self, message: str, *, state: str = "idle"):
        self.validation_hint.setText(message)
        self.validation_hint.setProperty("validationState", state if message else "")
        self.validation_hint.style().unpolish(self.validation_hint)
        self.validation_hint.style().polish(self.validation_hint)
        self.validation_hint.update()
        self.validation_hint.setVisible(bool(message))

    def _on_any_edit(self):
        # Any edit in plain view keeps save enabled
        if self.stack.currentWidget() is self.plain:
            self._update_save_enabled()

    def _on_table_selection_changed(self):
        has = bool(self._selected_rows())
        self.btn_del.setEnabled(has)
        self.btn_snap.setEnabled(has)
        self.btn_shift_minus.setEnabled(has)
        self.btn_shift_plus.setEnabled(has)
        self.shift_spin.setEnabled(has)
        self.btn_shift_selected.setEnabled(has)
        self.btn_shift_all_from_first.setEnabled(bool(self.table.rowCount()))
        self._refresh_row_styles()

    def _selected_rows(self) -> list[int]:
        model = self.table.selectionModel()
        if model is None:
            row = self.table.currentRow()
            return [row] if row >= 0 else []
        rows = sorted({index.row() for index in model.selectedRows()})
        if rows:
            return rows
        row = self.table.currentRow()
        return [row] if row >= 0 else []

    def _on_table_clicked_seek(self, row: int, col: int):
        it_time = self.table.item(row, 0)
        if not it_time:
            return
        ms = it_time.data(TIMESTAMP_MS_ROLE)
        if ms is None:
            return
        self.seekRequested.emit(int(ms))

    def _on_table_item_changed(self, item: QTableWidgetItem):
        # If user edited the Time cell, validate and update ms
        if item.column() != 0:
            return

        row = item.row()
        new_ms = _parse_ts_str(item.text())
        if new_ms is None:
            item.setData(TIMESTAMP_VALID_ROLE, False)
            item.setToolTip("Use mm:ss, mm:ss.xx or mm:ss.xxx")
            self._invalid_rows.add(row)
            self._set_validation_message(
                f"Line {row + 1}: timestamp must use mm:ss, mm:ss.xx or mm:ss.xxx.",
                state="error",
            )
            self._update_save_enabled()
            self._refresh_row_styles()
            return

        item.setData(TIMESTAMP_MS_ROLE, int(new_ms))
        item.setData(TIMESTAMP_VALID_ROLE, True)
        item.setToolTip("Timestamp is valid")
        item.setText(_ms_to_ts(int(new_ms)))  # normalize format
        self._invalid_rows.discard(row)
        if self._invalid_rows:
            next_row = min(self._invalid_rows)
            self._set_validation_message(
                f"Line {next_row + 1}: timestamp must use mm:ss, mm:ss.xx or mm:ss.xxx.",
                state="error",
            )
        else:
            self._set_validation_message("Timestamps look good.", state="success")
        self._rebuild_times_cache()
        self._update_save_enabled()
        self._refresh_row_styles()

    def _add_line_after_selection(self):
        row = self.table.currentRow()
        insert_at = row + 1 if row >= 0 else self.table.rowCount()

        # default time: current playback time
        ms = int(self._current_pos_ms)

        self.table.blockSignals(True)
        self.table.insertRow(insert_at)

        it_time = QTableWidgetItem(_ms_to_ts(ms))
        it_time.setData(TIMESTAMP_MS_ROLE, ms)
        it_time.setData(TIMESTAMP_VALID_ROLE, True)
        it_time.setFlags(it_time.flags() | Qt.ItemIsEditable)

        it_text = QTableWidgetItem("")
        it_text.setFlags(it_text.flags() | Qt.ItemIsEditable)

        self.table.setItem(insert_at, 0, it_time)
        self.table.setItem(insert_at, 1, it_text)
        self.table.blockSignals(False)

        self._rebuild_times_cache()
        self._refresh_row_styles()
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
        self._invalid_rows = {idx - 1 if idx > row else idx for idx in self._invalid_rows if idx != row}
        self._rebuild_times_cache()
        if self._invalid_rows:
            next_row = min(self._invalid_rows)
            self._set_validation_message(
                f"Line {next_row + 1}: timestamp must use mm:ss, mm:ss.xx or mm:ss.xxx.",
                state="error",
            )
        else:
            self._set_validation_message("")
        self._update_save_enabled()
        self._refresh_row_styles()

    def _snap_selected_line_to_current_time(self):
        row = self.table.currentRow()
        if row < 0:
            return

        it_time = self.table.item(row, 0)
        if not it_time:
            return

        ms = max(0, int(self._current_pos_ms) + int(self._reaction_delay_ms))
        self.table.blockSignals(True)
        it_time.setData(TIMESTAMP_MS_ROLE, ms)
        it_time.setData(TIMESTAMP_VALID_ROLE, True)
        it_time.setText(_ms_to_ts(ms))
        self.table.blockSignals(False)
        self._invalid_rows.discard(row)

        self._rebuild_times_cache()
        if self._invalid_rows:
            next_row = min(self._invalid_rows)
            self._set_validation_message(
                f"Line {next_row + 1}: timestamp must use mm:ss, mm:ss.xx or mm:ss.xxx.",
                state="error",
            )
        else:
            if self._reaction_delay_ms:
                direction = "earlier" if self._reaction_delay_ms < 0 else "later"
                self._set_validation_message(
                    f"Snapped line using {abs(self._reaction_delay_ms)} ms reaction delay ({direction}).",
                    state="success",
                )
            else:
                self._set_validation_message("Snapped selected line to current playback time.", state="success")
        self._update_save_enabled()
        self._refresh_row_styles()

    def _shift_selected_lines_by_custom_amount(self):
        delta_ms = int(round(float(self.shift_spin.value()) * 1000.0))
        self._shift_selected_lines(delta_ms)

    def _shift_selected_lines(self, delta_ms: int):
        rows = self._selected_rows()
        if not rows:
            return
        self._apply_delta_to_rows(rows, int(delta_ms))
        rendered = f"{int(delta_ms):+d} ms"
        line_word = "line" if len(rows) == 1 else "lines"
        self._set_validation_message(
            f"Shifted {len(rows)} selected {line_word} by {rendered}.",
            state="success",
        )

    def _shift_all_lines_from_first_delta(self):
        if self.table.rowCount() <= 0:
            return
        first_item = self.table.item(0, 0)
        if not first_item:
            return
        first_ms = int(first_item.data(TIMESTAMP_MS_ROLE) or 0)
        target_ms = max(0, int(self._current_pos_ms) + int(self._reaction_delay_ms))
        delta_ms = target_ms - first_ms
        if delta_ms == 0:
            self._set_validation_message("First line already matches the current playback time.", state="success")
            return
        self._apply_delta_to_rows(list(range(self.table.rowCount())), delta_ms)
        self._set_validation_message(
            f"Shifted all lines by {delta_ms:+d} ms using the first line as reference.",
            state="success",
        )

    def _apply_delta_to_rows(self, rows: list[int], delta_ms: int):
        if not rows:
            return
        self.table.blockSignals(True)
        for row in rows:
            it_time = self.table.item(row, 0)
            if not it_time:
                continue
            current_ms = int(it_time.data(TIMESTAMP_MS_ROLE) or 0)
            updated_ms = max(0, current_ms + int(delta_ms))
            it_time.setData(TIMESTAMP_MS_ROLE, updated_ms)
            it_time.setData(TIMESTAMP_VALID_ROLE, True)
            it_time.setText(_ms_to_ts(updated_ms))
            self._invalid_rows.discard(row)
        self.table.blockSignals(False)
        self._rebuild_times_cache()
        self._update_save_enabled()
        self._refresh_row_styles()

    def _emit_save(self):
        # Synced view: build LRC + plain
        if self.stack.currentWidget() is self.table:
            if self._invalid_rows:
                next_row = min(self._invalid_rows)
                self._set_validation_message(
                    f"Fix the timestamp on line {next_row + 1} before saving.",
                    state="error",
                )
                return
            pairs: List[Tuple[int, str]] = []
            for r in range(self.table.rowCount()):
                it_time = self.table.item(r, 0)
                it_text = self.table.item(r, 1)
                ms = int(it_time.data(TIMESTAMP_MS_ROLE) or 0) if it_time else 0
                text = it_text.text() if it_text else ""
                # Keep empty lines (timestamp-only)
                pairs.append((ms, text.rstrip()))

            # sort by time
            pairs.sort(key=lambda x: x[0])

            lrc_lines: list[str] = []
            for ms, text in pairs:
                t = _ms_to_ts(ms)
                if text.strip():
                    lrc_lines.append(f"[{t}] {text.strip()}")
                else:
                    # Timestamp-only line (blank lyric line)
                    lrc_lines.append(f"[{t}]")
            lrc = "\n".join(lrc_lines).strip()

            # Preserve blank lines in plain view
            plain = "\n".join([text.rstrip() for _, text in pairs]).rstrip()

            self.saveRequested.emit(lrc, plain)
            return

        # Plain view: save plain only
        if self.stack.currentWidget() is self.plain:
            txt = (self.plain.toPlainText() or "").strip()
            self.saveRequested.emit("", txt)
            return

    def set_save_feedback(self, state: str, message: str | None = None) -> None:
        self._set_button_feedback(self.btn_save, state, message)

    def set_publish_feedback(self, *, is_synced: bool, state: str, message: str | None = None) -> None:
        button = self.btn_publish_synced if is_synced else self.btn_publish_plain
        self._set_button_feedback(button, state, message)

    def _set_button_feedback(self, button: QPushButton, state: str, message: str | None = None) -> None:
        default_text = self._default_button_text.get(button, button.text())
        text = message or {
            "loading": "Working...",
            "success": "Done",
            "error": "Try Again",
        }.get(state, default_text)

        button.setText(text)
        button.setProperty("actionState", state if state != "idle" else "")
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()
        button.setEnabled(state != "loading")

        if state in {"success", "error"}:
            QTimer.singleShot(1800, lambda b=button, t=default_text: self._reset_button_feedback(b, t))

    def _reset_button_feedback(self, button: QPushButton, default_text: str) -> None:
        button.setText(default_text)
        button.setProperty("actionState", "")
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()
        if button is self.btn_save:
            self._update_save_enabled()
        elif button is self.btn_publish_synced:
            button.setEnabled(self._publish_synced_available)
        elif button is self.btn_publish_plain:
            button.setEnabled(self._publish_plain_available)
