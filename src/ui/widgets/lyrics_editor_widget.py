# ui/lyrics_view.py
from __future__ import annotations

import logging
import re
from bisect import bisect_right

from PySide6.QtCore import QEvent, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QSizePolicy,
    QWidget, QVBoxLayout, QLabel, QStackedWidget,
    QTextEdit, QTableWidget, QTableWidgetItem,
    QPushButton, QHBoxLayout, QDoubleSpinBox, QMenu
)

from ui.spacing import SPACE_2, SPACE_3, set_layout_spacing
from ui.style_loader import load_stylesheet
from ui.widgets.empty_state_widget import EmptyStateWidget
from ui.widgets.lyrics_editor_parts import FlowLayout, hotkeys as lyrics_editor_hotkeys
from core.utils import (
    LRC_TS_RE as _TS_RE,
    _ts_to_ms,
    ms_to_ts as _ms_to_ts,
    parse_ts_str as _parse_ts_str,
    parse_lrc,
)
from core.lyrics_validator import (
    LyricsValidationProblem,
    autofix_plain_lyrics,
    autofix_synced_lyrics,
    validate_plain_lyrics,
    validate_synced_lyrics,
)
from ui.hotkeys import HOTKEY_SPECS, effective_hotkey_text, lyrics_hotkey_defaults, normalize_hotkey_text

TIMESTAMP_MS_ROLE = Qt.ItemDataRole.UserRole
TIMESTAMP_VALID_ROLE = Qt.ItemDataRole.UserRole + 1
SHIFT_SPIN_MIN_WIDTH = 96
LINE_NUMBER_HEADER_WIDTH = 42
TIME_COLUMN = 0
TEXT_COLUMN = 1
LINE_NUMBER_COLUMN = 2
logger = logging.getLogger(__name__)


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
    propagateRequested = Signal(str, str)  # lrc_text, plain_text
    dirtyDraftChanged = Signal(str, str)  # lrc_text, plain_text
    discardDraftRequested = Signal()
    autoSyncRequested = Signal()
    downloadRequested = Signal()
    searchRequested = Signal()
    exportFilesRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._ui_scale: float = 1.0
        self._current_pos_ms: int = 0
        self._times: list[int] = []
        self._current_index: int = -1
        self._invalid_rows: set[int] = set()
        self._lint_rows: set[int] = set()
        self._row_validation_messages: dict[int, list[str]] = {}
        self._validation_problems: list[LyricsValidationProblem] = []
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
        self.header_widget = QWidget()
        self.header_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        header = QVBoxLayout(self.header_widget)
        set_layout_spacing(header, spacing=SPACE_2)

        title_row = QHBoxLayout()
        set_layout_spacing(title_row, spacing=SPACE_2)

        self.title = QLabel("Lyrics")
        self.title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.title.setObjectName("LyricsTitle")
        title_row.addWidget(self.title, 1)
        self.validation_badge = QLabel("")
        self.validation_badge.setObjectName("LyricsValidationBadge")
        self.validation_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.validation_badge.hide()
        title_row.addWidget(self.validation_badge)

        self.dirty_badge = QLabel("")
        self.dirty_badge.setObjectName("LyricsDirtyBadge")
        self.dirty_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        self.btn_auto_sync.setToolTip("Automatically synchronize lyrics using AI (requires torch and openai-whisper; Demucs is optional)")
        self.btn_auto_sync.hide()
        self.btn_auto_sync.clicked.connect(self.autoSyncRequested.emit)
        title_row.addWidget(self.btn_auto_sync)

        for title_control in (
            self.validation_badge,
            self.dirty_badge,
            self.btn_discard_draft,
            self.btn_show_diff,
            self.btn_switch_mode,
            self.btn_auto_sync,
        ):
            title_control.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        header.addLayout(title_row)

        toolbar = FlowLayout(spacing=SPACE_2)

        self._lyrics_hotkeys = lyrics_hotkey_defaults()

        self.btn_snap = QPushButton("Snap")
        self.btn_shift_minus = QPushButton("-0.1s")
        self.btn_shift_minus.setToolTip("Shift selected lines 100ms earlier (Left)")
        self.btn_shift_plus = QPushButton("+0.1s")
        self.btn_shift_plus.setToolTip("Shift selected lines 100ms later (Right)")
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
        self.btn_shift_all_from_first = QPushButton("Shift All from First")
        self.btn_add = QPushButton("+ Line")
        self.btn_add.setToolTip("Insert a new line after the current selection (Ctrl+N or Insert)")
        self.btn_del = QPushButton("Delete")
        self.btn_del.setToolTip("Delete the selected line (Delete)")
        self.btn_autofix = QPushButton("Autofix")
        self.btn_autofix.setObjectName("LyricsAutofix")
        self.btn_autofix.setToolTip("Automatically fix safe lyrics validation issues")
        self.btn_autofix.hide()
        self.btn_save = QPushButton("Save")
        self.btn_save.setToolTip("Save lyrics to the library (Ctrl+S)")
        self.btn_sync_others = QPushButton("Sync to Others")
        self.btn_sync_others.setToolTip("Copy the current lyrics to similar tracks")
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
        self.btn_sync_others.setEnabled(False)
        self.btn_export_files.setEnabled(False)

        self.btn_snap.clicked.connect(self._snap_selected_line_to_current_time)
        self.btn_shift_minus.clicked.connect(lambda: self._shift_selected_lines(-100))
        self.btn_shift_plus.clicked.connect(lambda: self._shift_selected_lines(100))
        self.btn_shift_selected.clicked.connect(self._shift_selected_lines_by_custom_amount)
        self.btn_shift_all_from_first.clicked.connect(self._shift_all_lines_from_first_delta)
        self.btn_add.clicked.connect(self._add_line_after_selection)
        self.btn_del.clicked.connect(self._delete_selected_line)
        self.btn_autofix.clicked.connect(self._autofix_validation_problems)
        self.btn_save.clicked.connect(self._emit_save)
        self.btn_sync_others.clicked.connect(self._emit_propagate)
        self.btn_export_files.clicked.connect(self.exportFilesRequested.emit)

        toolbar.addWidget(self.btn_snap)
        toolbar.addWidget(self.btn_shift_minus)
        toolbar.addWidget(self.btn_shift_plus)
        toolbar.addWidget(self.shift_spin)
        toolbar.addWidget(self.btn_shift_selected)
        toolbar.addWidget(self.btn_shift_all_from_first)
        toolbar.addWidget(self.btn_add)
        toolbar.addWidget(self.btn_del)
        toolbar.addWidget(self.btn_autofix)
        toolbar.addWidget(self.btn_save)
        toolbar.addWidget(self.btn_sync_others)
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
            self.btn_autofix,
            self.btn_save,
            self.btn_sync_others,
            self.btn_export_files,
            self.btn_publish_synced,
            self.btn_publish_plain,
        ):
            button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        toolbar.addWidget(self.btn_publish_synced)
        toolbar.addWidget(self.btn_publish_plain)

        header.addLayout(toolbar)

        root.addWidget(self.header_widget)

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
        self.empty_state.quaternaryActionTriggered.connect(self._start_ai_sync_from_empty_state)
        self.stack.addWidget(self.empty_state)

        # Plain editor (editable if you want)
        self.plain = QTextEdit()
        self.plain.setAcceptRichText(False)
        self.plain.setPlaceholderText("Lyrics will appear here")
        self.plain.textChanged.connect(self._on_any_edit)
        self.stack.addWidget(self.plain)

        # Synced editor table
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Time", "Text", "#"])
        line_header = self.table.verticalHeader()
        line_header.setVisible(False)
        line_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(self.table.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(self.table.EditTrigger.DoubleClicked | self.table.EditTrigger.EditKeyPressed)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.installEventFilter(self)
        self.table.viewport().installEventFilter(self)
        self.validation_hint.installEventFilter(self)
        self.table.cellClicked.connect(self._on_table_clicked_seek)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table.itemChanged.connect(self._on_table_item_changed)
        self.table.customContextMenuRequested.connect(self._show_synced_context_menu)

        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(TIME_COLUMN, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(TEXT_COLUMN, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(LINE_NUMBER_COLUMN, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(TIME_COLUMN, 95)
        self.table.setColumnWidth(LINE_NUMBER_COLUMN, LINE_NUMBER_HEADER_WIDTH)

        self.stack.addWidget(self.table)

        # Undo/redo shortcuts for the synced table
        self._shortcut_undo = QShortcut(QKeySequence.StandardKey.Undo, self)
        self._shortcut_undo.activated.connect(self._undo)
        self._shortcut_redo = QShortcut(QKeySequence.StandardKey.Redo, self)
        self._shortcut_redo.activated.connect(self._redo)
        self._shortcut_shift_minus = self._make_shortcut("Left", lambda: self._shift_selected_lines(-100))
        self._shortcut_shift_plus = self._make_shortcut("Right", lambda: self._shift_selected_lines(100))
        self._shortcut_add_line = self._make_shortcut("Insert", self._add_line_after_selection)
        self._shortcut_add_line_new = self._make_shortcut("Ctrl+N", self._add_line_after_selection)
        self._shortcut_add_line_before = self._make_shortcut("Ctrl+Shift+N", self._add_line_before_selection)
        self._shortcut_delete_line = self._make_shortcut("Delete", self._delete_selected_line)

        self._shortcut_snap: QShortcut | None = None
        self._shortcut_snap_enter: QShortcut | None = None
        self._shortcut_shift_selected: QShortcut | None = None
        self._shortcut_shift_selected_enter: QShortcut | None = None
        self._shortcut_shift_all: QShortcut | None = None
        self._shortcut_shift_all_enter: QShortcut | None = None
        self.set_hotkey_bindings(self._lyrics_hotkeys)

        self._default_button_text = {
            self.btn_save: "Save",
            self.btn_sync_others: "Sync to Others",
            self.btn_export_files: "Export Files",
            self.btn_publish_synced: "Publish Synced",
            self.btn_publish_plain: "Publish Plain",
        }

        self._apply_styles()
        self.show_none("Choose a track to review or edit its lyrics.")

    def _make_shortcut(self, key: str, callback) -> QShortcut:
        return lyrics_editor_hotkeys.make_shortcut(self, key, callback)

    @property
    def lyrics_hotkeys(self) -> dict[str, str]:
        return {
            action: effective_hotkey_text(binding, HOTKEY_SPECS[action])
            for action, binding in self._lyrics_hotkeys.items()
        }

    def set_ui_scale(self, scale: float) -> None:
        self._ui_scale = max(0.85, min(1.5, float(scale or 1.0)))
        self.shift_spin.setMinimumWidth(int(round(SHIFT_SPIN_MIN_WIDTH * self._ui_scale)))
        self.table.setColumnWidth(TIME_COLUMN, int(round(95 * self._ui_scale)))
        self.table.setColumnWidth(LINE_NUMBER_COLUMN, int(round(LINE_NUMBER_HEADER_WIDTH * self._ui_scale)))
        self.table.verticalHeader().setDefaultSectionSize(int(round(30 * self._ui_scale)))

    def set_hotkey_bindings(self, bindings: dict[str, dict[str, object]] | None) -> None:
        lyrics_editor_hotkeys.set_hotkey_bindings(self, bindings)

    def _replace_action_shortcuts(self, primary_attr: str, secondary_attr: str, key: str, callback) -> None:
        lyrics_editor_hotkeys.replace_action_shortcuts(self, primary_attr, secondary_attr, key, callback)

    def _replace_shortcut(self, attr_name: str, key: str | None, callback) -> None:
        lyrics_editor_hotkeys.replace_shortcut(self, attr_name, key, callback)

    @staticmethod
    def _shortcut_variants(key: str) -> tuple[str, str | None]:
        return lyrics_editor_hotkeys.shortcut_variants(key)

    def eventFilter(self, watched, event):
        if watched is self.validation_hint and event.type() == QEvent.Type.MouseButtonRelease:
            if self._validation_problems:
                self._jump_to_first_validation_problem()
                return True
        if watched in {self.table, self.table.viewport()} and event.type() == QEvent.Type.KeyPress:
            modifiers = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            if (
                event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}
                and modifiers == Qt.KeyboardModifier.NoModifier
                and self._handle_synced_table_enter()
            ):
                return True
        return super().eventFilter(watched, event)

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

        publish_synced_available = bool((lrc_lyrics or "").strip()) and not has_dirty_draft
        publish_plain_available = bool((txt_lyrics or "").strip()) and not has_dirty_draft
        self._set_dirty_badge(has_dirty_draft)

        # Prefer showing synced editor if we have LRC that parses
        if lrc:
            pairs = parse_lrc(lrc)
            if pairs:
                self._set_synced(pairs)
                self._set_publish_available(publish_synced_available, publish_plain_available)
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
                self._loading_track = False
                return

        # else fall back to plain
        if txt:
            self._set_plain(txt)
            self._set_publish_available(publish_synced_available, publish_plain_available)
        else:
            self._reset_state()
            self._set_publish_available(False, False)
            self.empty_state.configure(
                icon_name="audio-lines.svg",
                title="No lyrics available yet",
                body="Download lyrics from LRCLIB, write them manually, or start an AI auto-sync draft from the local audio file.",
                action_text="Download Lyrics",
                secondary_action_text="Search LRCLIB",
                tertiary_action_text="Write Lyrics",
                quaternary_action_text="Auto Sync",
            )
            self.stack.setCurrentWidget(self.empty_state)
        self._loading_track = False

    # --- internal helpers ---
    def _reset_state(self):
        self._times = []
        self._current_index = -1
        self._publish_synced_available = False
        self._publish_plain_available = False
        self._invalid_rows.clear()
        self._lint_rows.clear()
        self._row_validation_messages.clear()
        self._validation_problems = []
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.blockSignals(False)
        self._sync_line_numbers()
        self._set_validation_message("")
        self._set_validation_badge("")
        self.btn_snap.setEnabled(False)
        self.btn_shift_minus.setEnabled(False)
        self.btn_shift_plus.setEnabled(False)
        self.shift_spin.setEnabled(False)
        self.btn_shift_selected.setEnabled(False)
        self.btn_shift_all_from_first.setEnabled(False)
        self.btn_add.setEnabled(False)
        self.btn_del.setEnabled(False)
        self.btn_autofix.setEnabled(False)
        self.btn_autofix.hide()
        self.btn_save.setEnabled(False)
        self.btn_sync_others.setEnabled(False)
        self.btn_export_files.setEnabled(False)
        self._update_publish_enabled()
        self.btn_switch_mode.hide()
        self.btn_auto_sync.hide()

    def _set_dirty_badge(self, visible: bool) -> None:
        self._has_dirty_draft = bool(visible)
        self.dirty_badge.setText("Unsaved draft" if visible else "")
        self.dirty_badge.setVisible(bool(visible))
        self.btn_discard_draft.setVisible(bool(visible))
        self.btn_show_diff.setVisible(bool(visible))
        self._update_publish_enabled()

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
        self.btn_add.setEnabled(False)
        self.btn_del.setEnabled(False)
        self.btn_snap.setEnabled(False)
        self.btn_shift_minus.setEnabled(False)
        self.btn_shift_plus.setEnabled(False)
        self.shift_spin.setEnabled(False)
        self.btn_shift_selected.setEnabled(False)
        self.btn_shift_all_from_first.setEnabled(False)
        self.btn_export_files.setEnabled(True)
        self.btn_sync_others.setEnabled(True)
        self.btn_switch_mode.setText("Switch to Synced")
        self.btn_switch_mode.setVisible(True)
        self.btn_auto_sync.setVisible(True)
        self._validate_current_lyrics()

    def _start_writing_lyrics(self):
        """Switch to an empty plain editor so the user can write lyrics from scratch."""
        self._set_plain("")
        self.plain.setFocus()

    def _start_ai_sync_from_empty_state(self):
        """Expose AI sync from the empty state while keeping the regular editor visible."""
        self._start_writing_lyrics()
        self.autoSyncRequested.emit()

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
            self.table.setItem(row, LINE_NUMBER_COLUMN, self._line_number_item(row))
            self._times.append(ms)
        self._sync_line_numbers()
        self.table.blockSignals(False)
        self._rebuild_times_cache()
        self._validate_current_lyrics()
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
            self.table.setItem(row, LINE_NUMBER_COLUMN, self._line_number_item(row))

        self._sync_line_numbers()
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
        self.btn_export_files.setEnabled(True)
        self.btn_sync_others.setEnabled(True)
        self.btn_switch_mode.setText("Switch to Plain")
        self.btn_switch_mode.setVisible(True)
        self.btn_auto_sync.setVisible(True)
        self._validate_current_lyrics()

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
        muted_fg = QColor(STYLE_TOKENS.get("color-text-muted", "#94a3b8"))
        line_number_bg = QColor(STYLE_TOKENS.get("color-bg-control", "#3a3a3a"))

        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            is_current = row == current_row
            is_selected = row == selected_row
            is_invalid = row in self._invalid_rows or row in self._lint_rows

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
                if col == LINE_NUMBER_COLUMN:
                    item.setBackground(line_number_bg)
                    item.setForeground(invalid_fg if is_invalid else muted_fg)
                else:
                    if bg is None:
                        item.setBackground(Qt.GlobalColor.transparent)
                    else:
                        item.setBackground(bg)
                    item.setForeground(fg)
                item.setToolTip(self._row_validation_tooltip(row))
        self.table.blockSignals(False)

    def _update_save_enabled(self):
        if self.stack.currentWidget() is self.table:
            can_use_lyrics = not self._invalid_rows and not self._validation_problems
            self.btn_save.setEnabled(can_use_lyrics)
            self.btn_sync_others.setEnabled(can_use_lyrics)
        elif self.stack.currentWidget() is self.plain:
            can_use_lyrics = not self._validation_problems
            self.btn_save.setEnabled(can_use_lyrics)
            self.btn_sync_others.setEnabled(can_use_lyrics)
        else:
            self.btn_save.setEnabled(False)
            self.btn_sync_others.setEnabled(False)

    def _set_publish_available(self, synced_available: bool, plain_available: bool) -> None:
        self._publish_synced_available = bool(synced_available)
        self._publish_plain_available = bool(plain_available)
        self._update_publish_enabled()

    def _update_publish_enabled(self) -> None:
        if self.stack.currentWidget() is self.table:
            can_publish_current = not self._invalid_rows and not self._validation_problems
        elif self.stack.currentWidget() is self.plain:
            can_publish_current = not self._validation_problems
        else:
            can_publish_current = False

        synced_enabled = self._publish_synced_available and can_publish_current and not self._has_dirty_draft
        plain_enabled = self._publish_plain_available and can_publish_current and not self._has_dirty_draft

        self.btn_publish_synced.setEnabled(synced_enabled)
        self.btn_publish_plain.setEnabled(plain_enabled)
        self.btn_publish_synced.setToolTip(
            self._publish_tooltip(
                is_synced=True,
                available=self._publish_synced_available,
                can_publish_current=can_publish_current,
            )
        )
        self.btn_publish_plain.setToolTip(
            self._publish_tooltip(
                is_synced=False,
                available=self._publish_plain_available,
                can_publish_current=can_publish_current,
            )
        )

    def _publish_tooltip(self, *, is_synced: bool, available: bool, can_publish_current: bool) -> str:
        if not can_publish_current and self._validation_problems:
            return "Fix validation issues before publishing."
        if self._has_dirty_draft:
            return "Save the draft before publishing to LRCLIB."
        if available and can_publish_current:
            return "Publish synced (LRC) lyrics to LRCLIB" if is_synced else "Publish plain text lyrics to LRCLIB"
        lyric_kind = "synced" if is_synced else "plain"
        return f"No saved {lyric_kind} lyrics available to publish."

    def _set_validation_message(self, message: str, *, state: str = "idle"):
        self.validation_hint.setText(message)
        self.validation_hint.setProperty("validationState", state if message else "")
        if message and self._validation_problems:
            self.validation_hint.setCursor(Qt.CursorShape.PointingHandCursor)
            self.validation_hint.setToolTip("Click to jump to the first validation issue.")
        else:
            self.validation_hint.unsetCursor()
            self.validation_hint.setToolTip("")
        self.validation_hint.style().unpolish(self.validation_hint)
        self.validation_hint.style().polish(self.validation_hint)
        self.validation_hint.update()
        self.validation_hint.setVisible(bool(message))

    def _set_validation_badge(self, text: str, *, state: str = "") -> None:
        self.validation_badge.setText(text)
        self.validation_badge.setProperty("validationState", state if text else "")
        self.validation_badge.style().unpolish(self.validation_badge)
        self.validation_badge.style().polish(self.validation_badge)
        self.validation_badge.update()
        self.validation_badge.setVisible(bool(text))

    def _validate_current_lyrics(self, *, show_success: bool = False) -> bool:
        if self.stack.currentWidget() is self.table:
            problems = self._timestamp_problems() + validate_synced_lyrics(self._take_snapshot())
        elif self.stack.currentWidget() is self.plain:
            problems = validate_plain_lyrics(self.plain.toPlainText() or "")
        else:
            problems = []

        self._validation_problems = problems
        self._lint_rows = {problem.line - 1 for problem in problems if problem.line > 0}
        self._row_validation_messages = self._validation_messages_by_row(problems)
        can_autofix = any(problem.fixable for problem in problems)
        self.btn_autofix.setVisible(bool(problems))
        self.btn_autofix.setEnabled(can_autofix)

        if problems:
            self._set_validation_message(self._format_validation_message(problems), state="error")
            issue_word = "issue" if len(problems) == 1 else "issues"
            self._set_validation_badge(f"{len(problems)} {issue_word}", state="error")
        elif show_success:
            self._set_validation_message("Lyrics validation passed.", state="success")
            self._set_validation_badge("Valid", state="success")
        else:
            self._set_validation_message("")
            if self.stack.currentWidget() in {self.table, self.plain}:
                self._set_validation_badge("Valid", state="success")
            else:
                self._set_validation_badge("")

        self._update_save_enabled()
        self._update_publish_enabled()
        if self.stack.currentWidget() is self.table:
            self._refresh_row_styles()
        return not problems

    @staticmethod
    def _validation_messages_by_row(problems: list[LyricsValidationProblem]) -> dict[int, list[str]]:
        messages: dict[int, list[str]] = {}
        for problem in problems:
            if problem.line <= 0:
                continue
            messages.setdefault(problem.line - 1, []).append(problem.message)
        return messages

    def _row_validation_tooltip(self, row: int) -> str:
        messages = self._row_validation_messages.get(row, [])
        if not messages:
            return ""
        return "\n".join(messages)

    def _jump_to_first_validation_problem(self) -> None:
        first_problem = next((problem for problem in self._validation_problems if problem.line > 0), None)
        if first_problem is None:
            return
        row = max(0, first_problem.line - 1)

        if self.stack.currentWidget() is self.table:
            if row >= self.table.rowCount():
                return
            column = self._validation_problem_column(first_problem)
            target = self.table.item(row, column) or self.table.item(row, TEXT_COLUMN)
            self.table.setFocus()
            self.table.selectRow(row)
            self.table.setCurrentCell(row, column)
            if target is not None:
                self.table.scrollToItem(target, self.table.ScrollHint.PositionAtCenter)
            return

        if self.stack.currentWidget() is self.plain:
            block = self.plain.document().findBlockByNumber(row)
            if not block.isValid():
                return
            cursor = QTextCursor(block)
            self.plain.setTextCursor(cursor)
            self.plain.setFocus()
            self.plain.ensureCursorVisible()

    @staticmethod
    def _validation_problem_column(problem: LyricsValidationProblem) -> int:
        message = problem.message.lower()
        if "timestamp" in message or "monotonically" in message:
            return TIME_COLUMN
        return TEXT_COLUMN

    def _line_number_item(self, row: int) -> QTableWidgetItem:
        item = QTableWidgetItem(str(row + 1))
        self._apply_line_number_style(item)
        return item

    def _sync_line_numbers(self) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, LINE_NUMBER_COLUMN)
            if item is None:
                item = self._line_number_item(row)
                self.table.setItem(row, LINE_NUMBER_COLUMN, item)
            else:
                item.setText(str(row + 1))
                self._apply_line_number_style(item)

    @staticmethod
    def _apply_line_number_style(item: QTableWidgetItem) -> None:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setFlags(
            (item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            | Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
        )

    def _timestamp_problems(self) -> list[LyricsValidationProblem]:
        return [
            LyricsValidationProblem(
                line=row + 1,
                message="Timestamp must use mm:ss, mm:ss.xx or mm:ss.xxx.",
            )
            for row in sorted(self._invalid_rows)
        ]

    @staticmethod
    def _format_validation_message(problems: list[LyricsValidationProblem]) -> str:
        head = problems[:3]
        lines = [f"Line {problem.line}: {problem.message}" for problem in head]
        if len(problems) > len(head):
            lines.append(f"...and {len(problems) - len(head)} more issue(s).")
        return "\n".join(lines)

    def _on_any_edit(self):
        # Any edit in plain view keeps save enabled
        if self.stack.currentWidget() is self.plain:
            self._validate_current_lyrics()
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

    def _show_synced_context_menu(self, pos) -> None:
        clicked_row = self.table.rowAt(pos.y())
        selected_rows = self._selected_rows()
        if clicked_row >= 0 and clicked_row not in selected_rows:
            self.table.selectRow(clicked_row)
            selected_rows = [clicked_row]

        menu = QMenu(self.table)
        insert_above_action = menu.addAction("Insert Line Above")
        insert_below_action = menu.addAction("Insert Line Below")
        menu.addSeparator()

        copy_action = menu.addAction("Copy")
        copy_action.setEnabled(self.table.rowCount() > 0)

        copy_all_action = None
        if selected_rows and len(selected_rows) != self.table.rowCount():
            copy_all_action = menu.addAction("Copy All")

        paste_action = menu.addAction("Paste")
        paste_action.setEnabled(bool(QApplication.clipboard().text().strip()))

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == insert_above_action:
            self._add_line_before_selection()
        elif chosen == insert_below_action:
            self._add_line_after_selection()
        elif chosen == copy_action:
            self._copy_synced_selection_to_clipboard()
        elif copy_all_action is not None and chosen == copy_all_action:
            self._copy_synced_all_to_clipboard()
        elif chosen == paste_action:
            self._paste_synced_from_clipboard()

    def _copy_synced_selection_to_clipboard(self) -> None:
        rows = self._selected_rows() or list(range(self.table.rowCount()))
        self._copy_synced_rows_to_clipboard(rows)

    def _copy_synced_all_to_clipboard(self) -> None:
        self._copy_synced_rows_to_clipboard(list(range(self.table.rowCount())))

    def _copy_synced_rows_to_clipboard(self, rows: list[int]) -> None:
        text = self._synced_lrc_text_for_rows(rows)
        if not text:
            return
        QApplication.clipboard().setText(text)
        self._set_validation_message("Copied synced lyrics.", state="success")

    def _synced_lrc_text_for_rows(self, rows: list[int]) -> str:
        lines: list[str] = []
        for row in rows:
            if row < 0 or row >= self.table.rowCount():
                continue
            it_time = self.table.item(row, 0)
            it_text = self.table.item(row, 1)
            ms = int(it_time.data(TIMESTAMP_MS_ROLE) or 0) if it_time else 0
            text = it_text.text().strip() if it_text else ""
            timestamp = _ms_to_ts(ms)
            lines.append(f"[{timestamp}] {text}" if text else f"[{timestamp}]")
        return "\n".join(lines).strip()

    def _paste_synced_from_clipboard(self) -> bool:
        return self._paste_synced_text(QApplication.clipboard().text())

    def _paste_synced_text(self, text: str) -> bool:
        text = (text or "").strip()
        if not text:
            return False

        parsed = parse_lrc(text)
        pairs = parsed if parsed else [(0, line.rstrip()) for line in text.splitlines()]
        if not pairs:
            return False

        self._push_undo()
        self._restore_snapshot(pairs)
        if self.table.rowCount():
            self.table.selectRow(0)
            self.table.setCurrentCell(0, 1)
        if not self._invalid_rows and not self._validation_problems:
            self._set_validation_message("Pasted synced lyrics.", state="success")
        self._emit_dirty_draft_changed()
        return True

    def _on_table_clicked_seek(self, row: int, col: int):
        self._seek_to_table_row(row)

    def _handle_synced_table_enter(self) -> bool:
        if self.stack.currentWidget() is not self.table:
            return False
        row = self.table.currentRow()
        col = self.table.currentColumn()
        if row < 0 or col < 0:
            return False
        if self.table.state() == self.table.State.EditingState:
            return False
        if col == 0:
            item = self.table.item(row, 0)
            if item is None:
                return False
            self.table.editItem(item)
            return True
        if col == 1:
            self._seek_to_table_row(row)
            return True
        return False

    def _seek_to_table_row(self, row: int) -> None:
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
            self._validate_current_lyrics()
            self._refresh_row_styles()
            self._emit_dirty_draft_changed()
            return

        row = item.row()
        new_ms = _parse_ts_str(item.text())
        if new_ms is None:
            item.setData(TIMESTAMP_VALID_ROLE, False)
            item.setToolTip("Use mm:ss, mm:ss.xx or mm:ss.xxx")
            self._invalid_rows.add(row)
            self._validate_current_lyrics()
            self._refresh_row_styles()
            self._emit_dirty_draft_changed()
            return

        item.setData(TIMESTAMP_MS_ROLE, int(new_ms))
        item.setData(TIMESTAMP_VALID_ROLE, True)
        item.setToolTip("Timestamp is valid")
        item.setText(_ms_to_ts(int(new_ms)))  # normalize format
        self._invalid_rows.discard(row)
        self._rebuild_times_cache()
        self._validate_current_lyrics(show_success=True)
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
        row = self.table.currentRow()
        insert_at = row + 1 if row >= 0 else self.table.rowCount()
        self._insert_line_at(insert_at)

    def _add_line_before_selection(self):
        row = self.table.currentRow()
        insert_at = row if row >= 0 else 0
        self._insert_line_at(insert_at)

    def _insert_line_at(self, insert_at: int):
        self._push_undo()
        insert_at = max(0, min(int(insert_at), self.table.rowCount()))

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
        self.table.setItem(insert_at, LINE_NUMBER_COLUMN, self._line_number_item(insert_at))
        self._sync_line_numbers()
        self.table.blockSignals(False)

        self._rebuild_times_cache()
        self._refresh_row_styles()
        self.table.selectRow(insert_at)
        self.table.setCurrentCell(insert_at, 1)
        self.table.editItem(self.table.item(insert_at, 1))
        self._validate_current_lyrics()
        self._emit_dirty_draft_changed()

    def _delete_selected_line(self):
        rows = self._selected_rows()
        if not rows:
            return
        self._push_undo()
        self.table.blockSignals(True)
        for row in reversed(rows):
            self.table.removeRow(row)
        self._sync_line_numbers()
        self.table.blockSignals(False)
        self._invalid_rows = {
            r for r in range(self.table.rowCount())
            if self.table.item(r, 0) and self.table.item(r, 0).data(TIMESTAMP_VALID_ROLE) is False
        }
        self._rebuild_times_cache()
        self._validate_current_lyrics()
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
        if self._validate_current_lyrics():
            if self._reaction_delay_ms:
                direction = "earlier" if self._reaction_delay_ms < 0 else "later"
                self._set_validation_message(
                    f"Snapped line using {abs(self._reaction_delay_ms)} ms reaction delay ({direction}).",
                    state="success",
                )
            else:
                self._set_validation_message("Snapped selected line to current playback time.", state="success")
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
        self._validate_current_lyrics()
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

    def _autofix_validation_problems(self) -> None:
        if not any(problem.fixable for problem in self._validation_problems):
            return

        if self.stack.currentWidget() is self.table:
            self._push_undo()
            self._restore_snapshot(autofix_synced_lyrics(self._take_snapshot()))
        elif self.stack.currentWidget() is self.plain:
            fixed = autofix_plain_lyrics(self.plain.toPlainText() or "")
            if fixed == (self.plain.toPlainText() or ""):
                return
            self.plain.setPlainText(fixed)
        else:
            return

        if self._validate_current_lyrics(show_success=True):
            self._set_validation_message("Autofix applied. Lyrics validation passed.", state="success")
        else:
            self._set_validation_message(
                "Autofix applied. Some issues still need manual changes:\n"
                + self._format_validation_message(self._validation_problems),
                state="error",
            )
        self._refresh_row_styles()
        self._emit_dirty_draft_changed()

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
            if not self._validate_current_lyrics():
                return
            lrc, plain = self._current_lyrics_text()
            self.saveRequested.emit(lrc, plain)
            return

        # Plain view: save plain only
        if self.stack.currentWidget() is self.plain:
            if not self._validate_current_lyrics():
                return
            _lrc, txt = self._current_lyrics_text()
            self.saveRequested.emit("", txt)
            return

    def _emit_propagate(self):
        if self.stack.currentWidget() is self.table:
            if not self._validate_current_lyrics():
                return
            lrc, plain = self._current_lyrics_text()
            self.propagateRequested.emit(lrc, plain)
            return

        if self.stack.currentWidget() is self.plain:
            if not self._validate_current_lyrics():
                return
            _lrc, txt = self._current_lyrics_text()
            self.propagateRequested.emit("", txt)
            return

    def set_save_feedback(self, state: str, message: str | None = None) -> None:
        self._set_button_feedback(self.btn_save, state, message)

    def set_sync_others_feedback(self, state: str, message: str | None = None) -> None:
        self._set_button_feedback(self.btn_sync_others, state, message)

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
        elif button is self.btn_sync_others:
            self._update_save_enabled()
        elif button is self.btn_export_files:
            button.setEnabled(self.stack.currentWidget() in {self.table, self.plain})
        elif button is self.btn_publish_synced:
            self._update_publish_enabled()
        elif button is self.btn_publish_plain:
            self._update_publish_enabled()
