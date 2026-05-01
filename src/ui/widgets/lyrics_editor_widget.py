# ui/lyrics_view.py
from __future__ import annotations

import logging
import re
from bisect import bisect_right

from PySide6.QtCore import QRect, QSize, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QLayout,
    QSizePolicy,
    QWidget, QVBoxLayout, QLabel, QStackedWidget,
    QTextEdit, QTableWidget, QTableWidgetItem,
    QPushButton, QHBoxLayout, QDoubleSpinBox
)

from ui.spacing import SPACE_2, SPACE_3, set_layout_spacing
from ui.style_loader import load_stylesheet
from ui.widgets.empty_state_widget import EmptyStateWidget
from core.utils import (
    LRC_TS_RE as _TS_RE,
    _ts_to_ms,
    ms_to_ts as _ms_to_ts,
    parse_ts_str as _parse_ts_str,
    parse_lrc,
)

TIMESTAMP_MS_ROLE = Qt.ItemDataRole.UserRole
TIMESTAMP_VALID_ROLE = Qt.ItemDataRole.UserRole + 1
SHIFT_SPIN_MIN_WIDTH = 96
logger = logging.getLogger(__name__)


class FlowLayout(QLayout):
    def __init__(self, parent=None, *, spacing: int = SPACE_2, justify_rows: bool = True):
        super().__init__(parent)
        self._items = []
        self._justify_rows = bool(justify_rows)
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        y = effective.y()
        spacing = self.spacing()
        rows = []
        row = []
        row_width = 0
        row_height = 0

        for item in self._items:
            widget = item.widget()
            if widget is not None and not widget.isVisible():
                continue
            item_size = item.sizeHint()
            next_width = row_width + (spacing if row else 0) + item_size.width()
            if row and next_width > effective.width():
                rows.append((row, row_width, row_height))
                row = []
                row_width = 0
                row_height = 0
                next_width = item_size.width()
            row.append((item, item_size))
            row_width = next_width
            row_height = max(row_height, item_size.height())

        if row:
            rows.append((row, row_width, row_height))

        for row_items, row_width, row_height in rows:
            x = effective.x()
            extra = max(0, effective.width() - row_width)
            extra_each = extra // len(row_items) if self._justify_rows and row_items and not test_only else 0
            extra_remainder = extra % len(row_items) if self._justify_rows and row_items and not test_only else 0
            for index, (item, item_size) in enumerate(row_items):
                item_width = item_size.width() + extra_each + (1 if index < extra_remainder else 0)
                item_height = item_size.height()
                if not test_only:
                    item.setGeometry(QRect(x, y, item_width, item_height))
                x += item_width + spacing
            y += row_height + spacing

        if rows:
            y -= spacing
        return y - rect.y() + margins.bottom()


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
    dirtyDraftChanged = Signal(str, str)  # lrc_text, plain_text
    discardDraftRequested = Signal()
    autoSyncRequested = Signal()
    downloadRequested = Signal()
    searchRequested = Signal()
    exportFilesRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._current_pos_ms: int = 0
        self._times: list[int] = []
        self._current_index: int = -1
        self._invalid_rows: set[int] = set()
        self._default_button_text: dict[QPushButton, str] = {}
        self._publish_synced_available = False
        self._publish_plain_available = False
        self._loading_track = False
        self._has_dirty_draft = False
        self._reaction_delay_ms: int = 0
        self._current_position_provider = None
        self._saved_lrc: str = ""
        self._saved_txt: str = ""

        # Snapshot-based undo/redo for the synced table editor
        self._undo_stack: list[list[tuple[int, str]]] = []
        self._redo_stack: list[list[tuple[int, str]]] = []

        root = QVBoxLayout(self)
        set_layout_spacing(root, margins=SPACE_3, spacing=SPACE_2)

        # --- header ---
        header = QVBoxLayout()
        set_layout_spacing(header, spacing=SPACE_2)

        title_row = QHBoxLayout()
        set_layout_spacing(title_row, spacing=SPACE_2)

        self.title = QLabel("Lyrics")
        self.title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.title.setObjectName("LyricsTitle")
        title_row.addWidget(self.title, 1)
        self.dirty_badge = QLabel("")
        self.dirty_badge.setObjectName("LyricsDirtyBadge")
        self.dirty_badge.hide()
        title_row.addWidget(self.dirty_badge)

        self.btn_discard_draft = QPushButton("Discard")
        self.btn_discard_draft.setObjectName("LyricsDiscardDraft")
        self.btn_discard_draft.setToolTip("Discard draft and revert to saved lyrics")
        self.btn_discard_draft.hide()
        self.btn_discard_draft.clicked.connect(self.discardDraftRequested.emit)
        title_row.addWidget(self.btn_discard_draft)

        self.btn_show_diff = QPushButton("Diff")
        self.btn_show_diff.setObjectName("LyricsShowDiff")
        self.btn_show_diff.setToolTip("Show differences between saved and draft lyrics")
        self.btn_show_diff.hide()
        self.btn_show_diff.clicked.connect(self._show_diff)
        title_row.addWidget(self.btn_show_diff)

        self.btn_switch_mode = QPushButton("Switch to Synced")
        self.btn_switch_mode.setObjectName("LyricsSwitchMode")
        self.btn_switch_mode.setToolTip("Toggle between synced (timestamped) and plain text editing")
        self.btn_switch_mode.hide()
        self.btn_switch_mode.clicked.connect(self._toggle_editor_mode)
        title_row.addWidget(self.btn_switch_mode)

        self.btn_auto_sync = QPushButton("Auto Sync")
        self.btn_auto_sync.setObjectName("LyricsAutoSync")
        self.btn_auto_sync.setToolTip("Automatically synchronize lyrics using AI (requires torch, demucs, openai-whisper)")
        self.btn_auto_sync.hide()
        self.btn_auto_sync.clicked.connect(self.autoSyncRequested.emit)
        title_row.addWidget(self.btn_auto_sync)

        header.addLayout(title_row)

        toolbar = FlowLayout(spacing=SPACE_2)

        self.btn_snap = QPushButton("Snap")
        self.btn_snap.setToolTip("Set the selected line's timestamp to the current playback position")
        self.btn_shift_minus = QPushButton("-0.1s")
        self.btn_shift_minus.setToolTip("Shift selected lines 100ms earlier")
        self.btn_shift_plus = QPushButton("+0.1s")
        self.btn_shift_plus.setToolTip("Shift selected lines 100ms later")
        self.shift_spin = QDoubleSpinBox()
        self.shift_spin.setRange(-30.0, 30.0)
        self.shift_spin.setDecimals(2)
        self.shift_spin.setSingleStep(0.05)
        self.shift_spin.setValue(0.10)
        self.shift_spin.setSuffix(" s")
        self.shift_spin.setToolTip("Custom shift amount in seconds")
        self.shift_spin.setObjectName("LyricsShiftSpin")
        self.shift_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.shift_spin.setMinimumWidth(SHIFT_SPIN_MIN_WIDTH)
        self.btn_shift_selected = QPushButton("Shift Selected")
        self.btn_shift_selected.setToolTip("Shift selected lines by the custom amount")
        self.btn_shift_all_from_first = QPushButton("Shift All from First")
        self.btn_shift_all_from_first.setToolTip("Align all lines so the first line matches the current playback position")
        self.btn_add = QPushButton("+ Line")
        self.btn_add.setToolTip("Insert a new line after the current selection")
        self.btn_del = QPushButton("Delete")
        self.btn_del.setToolTip("Delete the selected line")
        self.btn_save = QPushButton("Save")
        self.btn_save.setToolTip("Save lyrics to the library (Ctrl+S)")
        self.btn_export_files = QPushButton("Export Files")
        self.btn_export_files.setToolTip("Export .lrc and .txt sidecar files next to the audio file")

        self.btn_snap.setEnabled(False)
        self.btn_shift_minus.setEnabled(False)
        self.btn_shift_plus.setEnabled(False)
        self.shift_spin.setEnabled(False)
        self.btn_shift_selected.setEnabled(False)
        self.btn_shift_all_from_first.setEnabled(False)
        self.btn_add.setEnabled(False)
        self.btn_del.setEnabled(False)
        self.btn_save.setEnabled(False)
        self.btn_export_files.setEnabled(False)

        self.btn_snap.clicked.connect(self._snap_selected_line_to_current_time)
        self.btn_shift_minus.clicked.connect(lambda: self._shift_selected_lines(-100))
        self.btn_shift_plus.clicked.connect(lambda: self._shift_selected_lines(100))
        self.btn_shift_selected.clicked.connect(self._shift_selected_lines_by_custom_amount)
        self.btn_shift_all_from_first.clicked.connect(self._shift_all_lines_from_first_delta)
        self.btn_add.clicked.connect(self._add_line_after_selection)
        self.btn_del.clicked.connect(self._delete_selected_line)
        self.btn_save.clicked.connect(self._emit_save)
        self.btn_export_files.clicked.connect(self.exportFilesRequested.emit)

        toolbar.addWidget(self.btn_snap)
        toolbar.addWidget(self.btn_shift_minus)
        toolbar.addWidget(self.btn_shift_plus)
        toolbar.addWidget(self.shift_spin)
        toolbar.addWidget(self.btn_shift_selected)
        toolbar.addWidget(self.btn_shift_all_from_first)
        toolbar.addWidget(self.btn_add)
        toolbar.addWidget(self.btn_del)
        toolbar.addWidget(self.btn_save)
        toolbar.addWidget(self.btn_export_files)

        self.btn_publish_synced = QPushButton("Publish Synced")
        self.btn_publish_synced.setToolTip("Publish synced (LRC) lyrics to LRCLIB")
        self.btn_publish_plain = QPushButton("Publish Plain")
        self.btn_publish_plain.setToolTip("Publish plain text lyrics to LRCLIB")
        self.btn_publish_synced.setEnabled(False)
        self.btn_publish_plain.setEnabled(False)
        self.btn_publish_synced.clicked.connect(lambda: self.publishSyncedRequested.emit())
        self.btn_publish_plain.clicked.connect(lambda: self.publishPlainRequested.emit())

        for button in (
            self.btn_snap,
            self.btn_shift_minus,
            self.btn_shift_plus,
            self.btn_shift_selected,
            self.btn_shift_all_from_first,
            self.btn_add,
            self.btn_del,
            self.btn_save,
            self.btn_export_files,
            self.btn_publish_synced,
            self.btn_publish_plain,
        ):
            button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        toolbar.addWidget(self.btn_publish_synced)
        toolbar.addWidget(self.btn_publish_plain)

        header.addLayout(toolbar)

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
        self.empty_state.secondaryActionTriggered.connect(self.searchRequested.emit)
        self.empty_state.tertiaryActionTriggered.connect(self._start_writing_lyrics)
        self.stack.addWidget(self.empty_state)

        # Plain editor (editable if you want)
        self.plain = QTextEdit()
        self.plain.setAcceptRichText(False)
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

        # Undo/redo shortcuts for the synced table
        self._shortcut_undo = QShortcut(QKeySequence.StandardKey.Undo, self)
        self._shortcut_undo.activated.connect(self._undo)
        self._shortcut_redo = QShortcut(QKeySequence.StandardKey.Redo, self)
        self._shortcut_redo.activated.connect(self._redo)

        self._default_button_text = {
            self.btn_save: "Save",
            self.btn_export_files: "Export Files",
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

    def set_current_position_provider(self, provider) -> None:
        self._current_position_provider = provider

    def _apply_styles(self):
        self.setStyleSheet(load_stylesheet("lyrics_editor.qss"))
        if hasattr(self, "empty_state") and self.empty_state:
            self.empty_state._apply_styles()

    def show_none(self, message: str):
        self._reset_state()
        self._set_dirty_badge(False)
        self.empty_state.configure(
            icon_name="audio-lines.svg",
            title="No track selected",
            body=message,
            action_text=None,
        )
        self.stack.setCurrentWidget(self.empty_state)

    def set_track_lyrics(
        self,
        title: str,
        txt_lyrics: str | None,
        lrc_lyrics: str | None,
        instrumental: bool,
        dirty_txt_lyrics: str | None = None,
        dirty_lrc_lyrics: str | None = None,
        dirty_lyrics_present: bool = False,
    ):
        self._loading_track = True
        self._saved_lrc = (lrc_lyrics or "").strip()
        self._saved_txt = (txt_lyrics or "").strip()
        self.title.setText(title or "Lyrics")
        has_dirty_draft = bool(
            dirty_lyrics_present
            and ((dirty_txt_lyrics or "").strip() or (dirty_lrc_lyrics or "").strip())
        )

        if instrumental:
            self._reset_state()
            self.empty_state.configure(
                icon_name="audio-lines.svg",
                title="Instrumental track",
                body="This track is marked as instrumental, so there are no lyrics to edit or publish.",
                action_text=None,
            )
            self.stack.setCurrentWidget(self.empty_state)
            self._set_dirty_badge(False)
            self._loading_track = False
            return

        lrc = (dirty_lrc_lyrics or lrc_lyrics or "").strip()
        txt = (dirty_txt_lyrics or txt_lyrics or "").strip()

        self._publish_synced_available = bool((lrc_lyrics or "").strip()) and not has_dirty_draft
        self._publish_plain_available = bool((txt_lyrics or "").strip()) and not has_dirty_draft
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
                self._set_dirty_badge(has_dirty_draft)
                self._loading_track = False
                return

        # else fall back to plain
        if txt:
            self._set_plain(txt)
            self._set_dirty_badge(has_dirty_draft)
        else:
            self._reset_state()
            self.empty_state.configure(
                icon_name="audio-lines.svg",
                title="No lyrics available yet",
                body="Download lyrics from LRCLIB to start editing, or search manually.",
                action_text="Download Lyrics",
                secondary_action_text="Search LRCLIB",
                tertiary_action_text="Write Lyrics",
            )
            self.stack.setCurrentWidget(self.empty_state)
            self._set_dirty_badge(False)
        self._loading_track = False

    # --- internal helpers ---
    def _reset_state(self):
        self._times = []
        self._current_index = -1
        self._publish_synced_available = False
        self._publish_plain_available = False
        self._invalid_rows.clear()
        self._undo_stack.clear()
        self._redo_stack.clear()
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
        self.btn_export_files.setEnabled(False)
        self.btn_switch_mode.hide()
        self.btn_auto_sync.hide()

    def _set_dirty_badge(self, visible: bool) -> None:
        self._has_dirty_draft = bool(visible)
        self.dirty_badge.setText("Unsaved draft" if visible else "")
        self.dirty_badge.setVisible(bool(visible))
        self.btn_discard_draft.setVisible(bool(visible))
        self.btn_show_diff.setVisible(bool(visible))

    def _show_diff(self) -> None:
        from ui.dialogs.lyrics_diff_dialog import LyricsDiffDialog

        saved = self._saved_lrc or self._saved_txt or ""
        _draft_lrc, draft_txt = self._current_lyrics_text()
        draft = _draft_lrc or draft_txt or ""

        dlg = LyricsDiffDialog(saved, draft, title="Lyrics Diff — Saved vs Draft", parent=self.window())
        dlg.exec()

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
        self.btn_export_files.setEnabled(True)
        self.btn_switch_mode.setText("Switch to Synced")
        self.btn_switch_mode.setVisible(True)
        self.btn_auto_sync.setVisible(True)

    def _start_writing_lyrics(self):
        """Switch to an empty plain editor so the user can write lyrics from scratch."""
        self._set_plain("")
        self.plain.setFocus()

    def _toggle_editor_mode(self):
        """Switch between synced (table) and plain text editing modes."""
        if self.stack.currentWidget() is self.table:
            # Synced → Plain: cache synced pairs so we can restore timestamps
            self._cached_synced_pairs = self._take_snapshot()
            lines: list[str] = []
            for r in range(self.table.rowCount()):
                it_text = self.table.item(r, 1)
                lines.append(it_text.text().rstrip() if it_text else "")
            txt = "\n".join(lines).rstrip()
            self._set_plain(txt)
            self._emit_dirty_draft_changed()
        elif self.stack.currentWidget() is self.plain:
            # Plain → Synced: parse pasted LRC first, otherwise restore cached timestamps.
            txt = (self.plain.toPlainText() or "").strip()
            if not txt:
                return
            parsed = parse_lrc(txt)
            if parsed:
                self._cached_synced_pairs = None
                self._set_synced(parsed)
                self._emit_dirty_draft_changed()
                return
            lines = txt.splitlines()
            cached = getattr(self, "_cached_synced_pairs", None)
            if cached and len(cached) == len(lines):
                pairs = [(ms, line.rstrip()) for (ms, _), line in zip(cached, lines)]
            else:
                pairs = [(0, line.rstrip()) for line in lines]
            self._cached_synced_pairs = None
            self._set_synced(pairs)
            self._emit_dirty_draft_changed()

    # --- Undo / Redo (snapshot-based for synced table) ---
    def _take_snapshot(self) -> list[tuple[int, str]]:
        """Capture all (ms, text) pairs from the synced table."""
        pairs: list[tuple[int, str]] = []
        for r in range(self.table.rowCount()):
            it_time = self.table.item(r, 0)
            it_text = self.table.item(r, 1)
            ms = int(it_time.data(TIMESTAMP_MS_ROLE) or 0) if it_time else 0
            text = it_text.text() if it_text else ""
            pairs.append((ms, text))
        return pairs

    def _push_undo(self):
        """Save current state to undo stack before a mutating operation."""
        if self.stack.currentWidget() is not self.table:
            return
        self._undo_stack.append(self._take_snapshot())
        self._redo_stack.clear()
        # Cap undo stack at 50 levels
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)

    def _restore_snapshot(self, pairs: list[tuple[int, str]]):
        """Restore the synced table from a snapshot."""
        self.table.blockSignals(True)
        self.table.setRowCount(len(pairs))
        self._times = []
        self._invalid_rows.clear()
        for row, (ms, text) in enumerate(pairs):
            it_time = QTableWidgetItem(_ms_to_ts(ms))
            it_time.setData(TIMESTAMP_MS_ROLE, ms)
            it_time.setData(TIMESTAMP_VALID_ROLE, True)
            it_time.setFlags(it_time.flags() | Qt.ItemIsEditable)
            it_text = QTableWidgetItem(text)
            it_text.setFlags(it_text.flags() | Qt.ItemIsEditable)
            self.table.setItem(row, 0, it_time)
            self.table.setItem(row, 1, it_text)
            self._times.append(ms)
        self.table.blockSignals(False)
        self._rebuild_times_cache()
        self._update_save_enabled()
        self._refresh_row_styles()

    def _undo(self):
        if self.stack.currentWidget() is self.plain:
            self.plain.undo()
            return
        if self.stack.currentWidget() is not self.table:
            return
        if not self._undo_stack:
            return
        self._redo_stack.append(self._take_snapshot())
        snapshot = self._undo_stack.pop()
        self._restore_snapshot(snapshot)
        self._set_validation_message("Undo", state="success")

    def _redo(self):
        if self.stack.currentWidget() is self.plain:
            self.plain.redo()
            return
        if self.stack.currentWidget() is not self.table:
            return
        if not self._redo_stack:
            return
        self._undo_stack.append(self._take_snapshot())
        snapshot = self._redo_stack.pop()
        self._restore_snapshot(snapshot)
        self._set_validation_message("Redo", state="success")

    def _set_synced(self, pairs: list[tuple[int, str]]):
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
        self.btn_export_files.setEnabled(True)
        self.btn_switch_mode.setText("Switch to Plain")
        self.btn_switch_mode.setVisible(True)
        self.btn_auto_sync.setVisible(True)

    def _rebuild_times_cache(self):
        times: list[int] = []
        for r in range(self.table.rowCount()):
            it_time = self.table.item(r, 0)
            ms = int(it_time.data(TIMESTAMP_MS_ROLE) or 0) if it_time else 0
            times.append(ms)
        self._times = times

    def _refresh_row_styles(self):
        from ui.theme_tokens import STYLE_TOKENS
        current_row = self._current_index if self.stack.currentWidget() is self.table else -1
        selected_row = self.table.currentRow()

        default_fg = QColor(STYLE_TOKENS.get("color-text", "#e5e7eb"))
        invalid_bg = QColor(STYLE_TOKENS.get("color-error-bg", "#3f1418"))
        invalid_fg = QColor(STYLE_TOKENS.get("color-error-text", "#fecaca"))
        current_selected_bg = QColor(STYLE_TOKENS.get("color-selection-bg", "#0b2942"))
        current_selected_fg = QColor(STYLE_TOKENS.get("color-selection-text", "#e0f2fe"))
        current_bg = QColor(STYLE_TOKENS.get("color-table-row-hover", "#0f2235"))
        current_fg = QColor(STYLE_TOKENS.get("color-accent-alt", "#bae6fd"))
        selected_bg = QColor(STYLE_TOKENS.get("color-bg-control", "#172554"))
        selected_fg = QColor(STYLE_TOKENS.get("color-text-strong", "#dbeafe"))

        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            is_current = row == current_row
            is_selected = row == selected_row
            is_invalid = row in self._invalid_rows

            bg = None
            fg = default_fg
            if is_invalid:
                bg = invalid_bg
                fg = invalid_fg
            elif is_current and is_selected:
                bg = current_selected_bg
                fg = current_selected_fg
            elif is_current:
                bg = current_bg
                fg = current_fg
            elif is_selected:
                bg = selected_bg
                fg = selected_fg

            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if not item:
                    continue
                if bg is None:
                    item.setBackground(Qt.GlobalColor.transparent)
                else:
                    item.setBackground(bg)
                item.setForeground(fg)
        self.table.blockSignals(False)

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
            self._emit_dirty_draft_changed()

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
        if not model:
            return []
        return sorted({index.row() for index in model.selectedRows()})

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
            self._emit_dirty_draft_changed()
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
            self._emit_dirty_draft_changed()
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
        self._emit_dirty_draft_changed()

    def _current_lyrics_text(self) -> tuple[str, str]:
        if self.stack.currentWidget() is self.table:
            pairs: list[tuple[int, str]] = []
            for r in range(self.table.rowCount()):
                it_time = self.table.item(r, 0)
                it_text = self.table.item(r, 1)
                ms = int(it_time.data(TIMESTAMP_MS_ROLE) or 0) if it_time else 0
                text = it_text.text() if it_text else ""
                pairs.append((ms, text.rstrip()))

            pairs.sort(key=lambda x: x[0])
            lrc_lines: list[str] = []
            for ms, text in pairs:
                t = _ms_to_ts(ms)
                lrc_lines.append(f"[{t}] {text.strip()}" if text.strip() else f"[{t}]")
            return "\n".join(lrc_lines).strip(), "\n".join([text.rstrip() for _, text in pairs]).rstrip()

        if self.stack.currentWidget() is self.plain:
            return "", (self.plain.toPlainText() or "").strip()

        return "", ""

    def _emit_dirty_draft_changed(self) -> None:
        if self._loading_track:
            return
        if self.stack.currentWidget() not in {self.table, self.plain}:
            return
        lrc, txt = self._current_lyrics_text()
        has_changes = (lrc.strip() != self._saved_lrc) or (txt.strip() != self._saved_txt)
        self._set_dirty_badge(has_changes)
        self.dirtyDraftChanged.emit(lrc, txt)

    def _add_line_after_selection(self):
        self._push_undo()
        row = self.table.currentRow()
        insert_at = row + 1 if row >= 0 else self.table.rowCount()

        # default time: current playback time
        ms = int(self._current_playback_ms())

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
        self._emit_dirty_draft_changed()

    def _delete_selected_line(self):
        rows = self._selected_rows()
        if not rows:
            return
        self._push_undo()
        self.table.blockSignals(True)
        for row in reversed(rows):
            self.table.removeRow(row)
        self.table.blockSignals(False)
        self._invalid_rows = {
            r for r in range(self.table.rowCount())
            if self.table.item(r, 0) and self.table.item(r, 0).data(TIMESTAMP_VALID_ROLE) is False
        }
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
        self._emit_dirty_draft_changed()

    def _snap_selected_line_to_current_time(self):
        row = self.table.currentRow()
        if row < 0:
            return

        it_time = self.table.item(row, 0)
        if not it_time:
            return

        self._push_undo()
        ms = max(0, int(self._current_playback_ms()) + int(self._reaction_delay_ms))
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
        self._emit_dirty_draft_changed()

    def _shift_selected_lines_by_custom_amount(self):
        delta_ms = int(round(float(self.shift_spin.value()) * 1000.0))
        self._shift_selected_lines(delta_ms)

    def _shift_selected_lines(self, delta_ms: int):
        rows = self._selected_rows()
        if not rows:
            return
        if not self._apply_delta_to_rows(rows, delta_ms):
            return
        rendered = f"{delta_ms:+d} ms"
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
        target_ms = max(0, int(self._current_playback_ms()) + int(self._reaction_delay_ms))
        delta_ms = target_ms - first_ms
        if delta_ms == 0:
            self._set_validation_message("First line already matches the current playback time.", state="success")
            return
        if not self._apply_delta_to_rows(list(range(self.table.rowCount())), delta_ms):
            return
        self._set_validation_message(
            f"Shifted all lines by {delta_ms:+d} ms using the first line as reference.",
            state="success",
        )

    def _apply_delta_to_rows(self, rows: list[int], delta_ms: int) -> bool:
        if not rows:
            return False
        collapse_rows = self._rows_that_would_collapse_to_zero(rows, delta_ms)
        if len(collapse_rows) > 1:
            self._set_validation_message(
                "Shift cancelled because multiple selected lines would collapse to 00:00.00.",
                state="error",
            )
            return False
        self._push_undo()
        self.table.blockSignals(True)
        for row in rows:
            it_time = self.table.item(row, 0)
            if not it_time:
                continue
            current_ms = int(it_time.data(TIMESTAMP_MS_ROLE) or 0)
            updated_ms = max(0, current_ms + delta_ms)
            it_time.setData(TIMESTAMP_MS_ROLE, updated_ms)
            it_time.setData(TIMESTAMP_VALID_ROLE, True)
            it_time.setText(_ms_to_ts(updated_ms))
            self._invalid_rows.discard(row)
        self.table.blockSignals(False)
        self._rebuild_times_cache()
        self._update_save_enabled()
        self._refresh_row_styles()
        self._emit_dirty_draft_changed()
        return True

    def _rows_that_would_collapse_to_zero(self, rows: list[int], delta_ms: int) -> list[int]:
        collapse_rows: list[int] = []
        if delta_ms >= 0:
            return collapse_rows
        for row in rows:
            it_time = self.table.item(row, 0)
            if not it_time:
                continue
            current_ms = int(it_time.data(TIMESTAMP_MS_ROLE) or 0)
            if current_ms + delta_ms <= 0:
                collapse_rows.append(row)
        return collapse_rows

    def _current_playback_ms(self) -> int:
        provider = self._current_position_provider
        if provider is not None:
            try:
                return int(provider())
            except (TypeError, ValueError, AttributeError) as exc:
                logger.warning("Failed to get playback position from provider: %s", exc)
        return int(self._current_pos_ms)

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
            lrc, plain = self._current_lyrics_text()
            self.saveRequested.emit(lrc, plain)
            return

        # Plain view: save plain only
        if self.stack.currentWidget() is self.plain:
            _lrc, txt = self._current_lyrics_text()
            self.saveRequested.emit("", txt)
            return

    def set_save_feedback(self, state: str, message: str | None = None) -> None:
        self._set_button_feedback(self.btn_save, state, message)

    def set_publish_feedback(self, *, is_synced: bool, state: str, message: str | None = None) -> None:
        button = self.btn_publish_synced if is_synced else self.btn_publish_plain
        self._set_button_feedback(button, state, message)

    def set_export_feedback(self, state: str, message: str | None = None) -> None:
        self._set_button_feedback(self.btn_export_files, state, message)

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
        elif button is self.btn_export_files:
            button.setEnabled(self.stack.currentWidget() in {self.table, self.plain})
        elif button is self.btn_publish_synced:
            button.setEnabled(self._publish_synced_available)
        elif button is self.btn_publish_plain:
            button.setEnabled(self._publish_plain_available)
