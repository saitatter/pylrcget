# ui/lyrics_view.py
from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QStackedWidget,
    QTextEdit, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem
)

from PySide6.QtWidgets import QPushButton, QHBoxLayout

_TS_RE = re.compile(r"\[(\d+):(\d+)(?:\.(\d+))?\]")

def _ts_to_ms(mm: str, ss: str, frac: str | None) -> int:
    m = int(mm)
    s = int(ss)
    if frac is None:
        ms = 0
    else:
        # lrc fractional can be 2 or 3 digits; normalize
        frac = frac.strip()
        if len(frac) == 1:
            ms = int(frac) * 100
        elif len(frac) == 2:
            ms = int(frac) * 10
        else:
            ms = int(frac[:3])
    return (m * 60 + s) * 1000 + ms

def ms_to_tag(ms: int) -> str:
    ms = max(0, int(ms))
    total_s = ms // 1000
    m = total_s // 60
    s = total_s % 60
    cs = (ms % 1000) // 10  # centiseconds
    return f"{m:02d}:{s:02d}.{cs:02d}"

def tag_to_ms(tag: str) -> int | None:
    # accepts mm:ss.xx or m:ss.xx
    try:
        tag = (tag or "").strip()
        if not tag:
            return None
        if "." in tag:
            left, frac = tag.split(".", 1)
        else:
            left, frac = tag, "00"
        mm, ss = left.split(":", 1)
        m = int(mm)
        s = int(ss)
        frac = (frac + "00")[:2]
        cs = int(frac)
        return (m * 60 + s) * 1000 + cs * 10
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

        # ignore metadata (common lrc headers)
        if line.startswith("[ar:") or line.startswith("[ti:") or line.startswith("[al:") or line.startswith("[by:") or line.startswith("[offset:") or line.startswith("[au:"):
            continue

        matches = list(_TS_RE.finditer(line))
        if not matches:
            continue

        # text after last timestamp
        text = _TS_RE.sub("", line).strip()
        if not text:
            # allow empty lines, but usually we skip
            continue

        for m in matches:
            t = _ts_to_ms(m.group(1), m.group(2), m.group(3))
            out.append((t, text))

    out.sort(key=lambda x: x[0])
    return out


class LyricsView(QWidget):
    """
    Right-side lyrics panel:
      - Synced: QListWidget with timestamps, highlight current line
      - Plain: QTextEdit read-only
      - None/instrumental: message
    """
    seekRequested = Signal(int)          # ms
    publishSyncedRequested = Signal()
    publishPlainRequested = Signal()
    saveRequested = Signal(str, str)     # lrc, txt  (dacă nu o ai deja)
    embedRequested = Signal()            # 👉 nou

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LyricsRoot")

        self._times = []
        self._dirty = False
        self._last_loaded_lrc = ""
        self._last_loaded_txt = ""

        self._current_index: int = -1
        self._user_scrolling: bool = False

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)

        self.title = QLabel("Lyrics")
        self.title.setObjectName("LyricsTitle")
        self.title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.addWidget(self.title, 1)

        self.btn_publish_synced = QPushButton("Publish Synced")
        self.btn_publish_plain = QPushButton("Publish Plain")
        self.btn_publish_synced.setEnabled(False)
        self.btn_publish_plain.setEnabled(False)

        self.btn_publish_synced.clicked.connect(lambda: self.publishSyncedRequested.emit())
        self.btn_publish_plain.clicked.connect(lambda: self.publishPlainRequested.emit())

        # 👉 nou: buton Embed
        self.btn_embed = QPushButton("Embed in file")
        self.btn_embed.setEnabled(False)
        self.btn_embed.clicked.connect(lambda: self.embedRequested.emit())

        header.addWidget(self.btn_publish_synced)
        header.addWidget(self.btn_publish_plain)
        header.addWidget(self.btn_embed)

        root.addLayout(header)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.btn_save = QPushButton("Save")
        self.btn_revert = QPushButton("Revert")
        self.btn_add = QPushButton("Add line")
        self.btn_del = QPushButton("Delete")
        self.btn_shift_m = QPushButton("Shift -200ms")
        self.btn_shift_p = QPushButton("Shift +200ms")

        for b in [self.btn_save, self.btn_revert, self.btn_add, self.btn_del, self.btn_shift_m, self.btn_shift_p]:
            b.setEnabled(False)

        controls.addWidget(self.btn_save)
        controls.addWidget(self.btn_revert)
        controls.addSpacing(12)
        controls.addWidget(self.btn_add)
        controls.addWidget(self.btn_del)
        controls.addSpacing(12)
        controls.addWidget(self.btn_shift_m)
        controls.addWidget(self.btn_shift_p)
        controls.addStretch(1)

        
        root.addLayout(controls)

        self.btn_save.clicked.connect(self._save_clicked)
        self.btn_revert.clicked.connect(self._revert_clicked)
        self.btn_add.clicked.connect(self._add_clicked)
        self.btn_del.clicked.connect(self._delete_clicked)
        self.btn_shift_m.clicked.connect(lambda: self._shift_all(-200))
        self.btn_shift_p.clicked.connect(lambda: self._shift_all(+200))

        # 0) message
        self.msg = QLabel("No lyrics")
        self.msg.setObjectName("LyricsMessage")
        self.msg.setAlignment(Qt.AlignCenter)
        self.msg.setWordWrap(True)
        self.stack.addWidget(self.msg)

        # 1) plain lyrics
        self.plain = QTextEdit()
        self.plain.setReadOnly(True)
        self.plain.setPlaceholderText("No lyrics")
        self.stack.addWidget(self.plain)

        # 2) synced lyrics (editable)
        self.synced = QTreeWidget()
        self.synced.setColumnCount(2)
        self.synced.setHeaderLabels(["Time", "Text"])
        self.synced.setRootIsDecorated(False)
        self.synced.setAlternatingRowColors(True)
        self.synced.setSelectionMode(self.synced.SelectionMode.SingleSelection)
        self.synced.setEditTriggers(
            self.synced.EditTrigger.DoubleClicked
            | self.synced.EditTrigger.EditKeyPressed
            | self.synced.EditTrigger.SelectedClicked
        )
        self.synced.setUniformRowHeights(True)
        self.synced.itemClicked.connect(self._on_synced_item_clicked)
        self.synced.itemChanged.connect(self._on_synced_item_changed)
        self.stack.addWidget(self.synced)

        self.synced.setStyleSheet("""
            QTreeWidget { border: 1px solid #3333; border-radius: 10px; }
            QTreeWidget::item { padding: 6px; }
            QHeaderView::section { padding: 6px; font-weight: 600; border: none; }
            """)

        self.show_none("No track selected")
        self._apply_styles()

    # --- public API ---
    def show_none(self, message: str):
        self._reset_synced()
        self.msg.setText(message)
        self.stack.setCurrentWidget(self.msg)
        self._set_edit_enabled(False)
        self._dirty = False
        self._last_loaded_lrc = ""
        self._last_loaded_txt = ""

    def set_track_lyrics(self, title: str, txt_lyrics: str | None, lrc_lyrics: str | None, instrumental: bool):
        self.title.setText(title or "Lyrics")

        if instrumental:
            self.btn_publish_synced.setEnabled(False)
            self.btn_publish_plain.setEnabled(False)
            self.btn_embed.setEnabled(False)
            self.show_none("Instrumental")
            return

        lrc = (lrc_lyrics or "").strip()
        txt = (txt_lyrics or "").strip()

        has_synced = bool(lrc)
        has_plain = bool(txt)

        self.btn_publish_synced.setEnabled(has_synced)
        self.btn_publish_plain.setEnabled(has_plain)
        self.btn_embed.setEnabled(has_synced or has_plain)

        # aici păstrezi logica ta de afișare:
        if has_synced:
            pairs = parse_lrc(lrc)
            if pairs:
                self._set_synced(pairs)
                return

        if has_plain:
            self._set_plain(txt)
            return

        self.show_none("No lyrics")
    
    def _set_message(self, message: str):
        self._reset_synced()
        self.msg.setText(message)
        self.stack.setCurrentWidget(self.msg)

    def _set_edit_enabled(self, enabled: bool):
        for b in [self.btn_save, self.btn_revert, self.btn_add, self.btn_del, self.btn_shift_m, self.btn_shift_p]:
            b.setEnabled(enabled)

    def on_player_position(self, ms: int):
        if self.stack.currentWidget() is not self.synced:
            return
        if not self._times:
            return

        pos = int(ms)
        idx = bisect_right(self._times, pos) - 1
        if idx < 0:
            idx = 0
        if idx == self._current_index:
            return
        self._current_index = idx

        item = self.synced.topLevelItem(idx)
        if not item:
            return

        self.synced.blockSignals(True)
        self.synced.setCurrentItem(item)
        self.synced.blockSignals(False)
        self.synced.scrollToItem(item, self.synced.ScrollHint.PositionAtCenter)

    # --- internals ---
    def _reset_synced(self):
        self._times = []
        self._current_index = -1
        self.synced.clear()

    def _set_plain(self, txt: str):
        self._reset_synced()
        self.plain.setPlainText(txt)
        self.stack.setCurrentWidget(self.plain)
        self._set_edit_enabled(False)
        self._dirty = False
        self._last_loaded_lrc = ""
        self._last_loaded_txt = (txt or "").strip()

    def _set_synced(self, pairs: List[Tuple[int, str]]):
        # cel mai simplu: refolosește funcția ta deja corectă
        self._set_synced_from_pairs(pairs)

    def _set_synced_from_pairs(self, pairs: list[tuple[int, str]]):
        self._reset_synced()
        blocker = QSignalBlocker(self.synced)
        try:
            for ms, text in pairs:
                it = QTreeWidgetItem([ms_to_tag(ms), text])
                it.setData(0, Qt.ItemDataRole.UserRole, int(ms))
                it.setFlags(it.flags() | Qt.ItemIsEditable)
                self.synced.addTopLevelItem(it)
                self._times.append(int(ms))
            self.synced.resizeColumnToContents(0)
            self.stack.setCurrentWidget(self.synced)
        finally:
            del blocker

        # ✅ enable edit controls
        self._set_edit_enabled(True)

        # ✅ remember loaded state for Revert
        lrc = self._serialize_lrc_from_tree()
        self._last_loaded_lrc = lrc
        self._last_loaded_txt = self._plain_from_lrc(lrc) if lrc else ""
        self._dirty = False

    def _on_synced_item_clicked(self, item: QTreeWidgetItem, col: int):
        ms = item.data(0, Qt.ItemDataRole.UserRole)
        if ms is None:
            ms = tag_to_ms(item.text(0))
        if ms is None:
            return
        self.seekRequested.emit(int(ms))
    
    def _on_synced_item_changed(self, item: QTreeWidgetItem, col: int):
        # validate time edits
        ms = tag_to_ms(item.text(0))
        if ms is None:
            # revert invalid
            old_ms = item.data(0, Qt.ItemDataRole.UserRole)
            if old_ms is not None:
                item.setText(0, ms_to_tag(int(old_ms)))
            return

        item.setData(0, Qt.ItemDataRole.UserRole, int(ms))

        # rebuild times array (must stay sorted by UI order)
        self._times = []
        for i in range(self.synced.topLevelItemCount()):
            it = self.synced.topLevelItem(i)
            v = it.data(0, Qt.ItemDataRole.UserRole)
            self._times.append(int(v) if v is not None else 0)

        self._dirty = True

    def _serialize_lrc_from_tree(self) -> str:
        lines = []
        for i in range(self.synced.topLevelItemCount()):
            it = self.synced.topLevelItem(i)
            ms = int(it.data(0, Qt.ItemDataRole.UserRole) or 0)
            text = (it.text(1) or "").rstrip()
            if not text:
                continue
            lines.append(f"[{ms_to_tag(ms)}]{text}")
        return "\n".join(lines).strip()

    def _strip_timestamps(self, lrc: str) -> str:
        # plainLyrics = remove [mm:ss.xx]
        out_lines = []
        for line in lrc.splitlines():
            # remove leading [..] blocks
            while line.startswith("[") and "]" in line:
                line = line.split("]", 1)[1].lstrip()
            out_lines.append(line)
        return "\n".join(out_lines).strip()
    
    def _plain_from_lrc(self, lrc: str) -> str:
        return self._strip_timestamps(lrc)  # folosește funcția ta existentă

    def _save_clicked(self):
        if self.stack.currentWidget() is self.synced:
            lrc = self._serialize_lrc_from_tree()
            txt = self._plain_from_lrc(lrc) if lrc else ""
            self.saveRequested.emit(lrc, txt)
            self._dirty = False
            self._last_loaded_lrc = lrc
            self._last_loaded_txt = txt
        elif self.stack.currentWidget() is self.plain:
            txt = (self.plain.toPlainText() or "").strip()
            self.saveRequested.emit("", txt)
            self._dirty = False
            self._last_loaded_lrc = ""
            self._last_loaded_txt = txt
    
    def _revert_clicked(self):
        # reload last_loaded state in UI
        lrc = self._last_loaded_lrc
        txt = self._last_loaded_txt

        if lrc:
            pairs = parse_lrc(lrc)
            self._set_synced_from_pairs(pairs)
        elif txt:
            self._set_plain(txt)
        else:
            self._set_message("No lyrics")

        self._dirty = False

    def _add_clicked(self):
        # add AFTER selected row; if none selected -> append
        cur = self.synced.currentItem()

        # pick a default time: same as current line if possible
        base_ms = 0
        insert_idx = self.synced.topLevelItemCount()  # default append

        if cur:
            base_ms = int(cur.data(0, Qt.ItemDataRole.UserRole) or 0)
            cur_idx = self.synced.indexOfTopLevelItem(cur)
            if cur_idx >= 0:
                insert_idx = cur_idx + 1

        it = QTreeWidgetItem([ms_to_tag(base_ms), ""])
        it.setData(0, Qt.ItemDataRole.UserRole, int(base_ms))
        it.setFlags(it.flags() | Qt.ItemIsEditable)

        self.synced.insertTopLevelItem(insert_idx, it)
        self.synced.setCurrentItem(it)
        self.synced.scrollToItem(it, self.synced.ScrollHint.PositionAtCenter)
        self.synced.editItem(it, 1)

        # rebuild times array to match UI order
        self._times = [
            int(self.synced.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) or 0)
            for i in range(self.synced.topLevelItemCount())
        ]

        self._dirty = True

    def _delete_clicked(self):
        it = self.synced.currentItem()
        if not it:
            return
        idx = self.synced.indexOfTopLevelItem(it)
        if idx >= 0:
            self.synced.takeTopLevelItem(idx)
            self._dirty = True
            # rebuild times
            self._times = [int(self.synced.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) or 0)
                        for i in range(self.synced.topLevelItemCount())]
    
    def _shift_all(self, delta_ms: int):
        if self.stack.currentWidget() is not self.synced:
            return
        blocker = QSignalBlocker(self.synced)
        try:
            for i in range(self.synced.topLevelItemCount()):
                it = self.synced.topLevelItem(i)
                ms = int(it.data(0, Qt.ItemDataRole.UserRole) or 0)
                ms2 = max(0, ms + int(delta_ms))
                it.setData(0, Qt.ItemDataRole.UserRole, ms2)
                it.setText(0, ms_to_tag(ms2))
            self._times = [int(self.synced.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) or 0)
                        for i in range(self.synced.topLevelItemCount())]
            self._dirty = True
        finally:
            del blocker

    def _apply_styles(self):
        self.setStyleSheet("""
        QWidget#LyricsRoot {
            background-color: #050711;
            border-radius: 14px;
            border: 1px solid #1b2338;
        }

        QLabel {
            color: #e5e9f0;
        }

        /* Header: titlu + butoane publish */
        #LyricsTitle {
            font-size: 15px;
            font-weight: 600;
            color: #f8fafc;
        }

        QPushButton {
            background-color: #111827;
            border-radius: 999px;
            padding: 4px 10px;
            border: 1px solid #1f2937;
            color: #e5e7eb;
            font-size: 11px;
        }
        QPushButton:hover {
            border-color: #38bdf8;
            background-color: #020617;
        }
        QPushButton:disabled {
            color: #6b7280;
            border-color: #1f2937;
            background-color: #020617;
        }

        /* Plain text editor */
        QTextEdit {
            background-color: #020617;
            border-radius: 10px;
            border: 1px solid #111827;
            padding: 8px;
            color: #e5e7eb;
            font-family: Consolas, "JetBrains Mono", "Fira Code", monospace;
            font-size: 12px;
        }

        /* Synced list */
        QListWidget {
            background-color: #020617;
            border-radius: 10px;
            border: 1px solid #111827;
            padding: 4px;
            color: #e5e7eb;
            font-family: "Inter", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            font-size: 13px;
        }

        QListWidget::item {
            padding: 6px 10px;
            margin: 2px 0;
        }

        /* current line highlight */
        QListWidget::item:selected {
            background-color: qlineargradient(
                x1:0, y1:0, x2:1, y2:0,
                stop:0 #0ea5e9,
                stop:1 #6366f1
            );
            color: #0b1020;
            border-radius: 8px;
        }

        /* message label (No lyrics / Instrumental) */
        QLabel#LyricsMessage {
            color: #9ca3af;
            font-size: 13px;
        }
        """)
