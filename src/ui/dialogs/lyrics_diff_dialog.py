"""Side-by-side lyrics diff dialog."""
from __future__ import annotations

import difflib

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
)


class LyricsDiffDialog(QDialog):
    """Show side-by-side diff between saved and draft lyrics."""

    def __init__(
        self,
        saved_text: str,
        draft_text: str,
        *,
        title: str = "Lyrics Diff",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(800, 500)

        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: saved
        left_label = QLabel("Saved")
        left_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_label.setStyleSheet("font-weight: bold;")
        self.left_edit = QTextEdit()
        self.left_edit.setReadOnly(True)
        left_w = _make_panel(left_label, self.left_edit)
        splitter.addWidget(left_w)

        # Right: draft
        right_label = QLabel("Draft")
        right_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_label.setStyleSheet("font-weight: bold;")
        self.right_edit = QTextEdit()
        self.right_edit.setReadOnly(True)
        right_w = _make_panel(right_label, self.right_edit)
        splitter.addWidget(right_w)

        splitter.setSizes([400, 400])
        layout.addWidget(splitter, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._populate_diff(saved_text or "", draft_text or "")

    def _populate_diff(self, saved: str, draft: str) -> None:
        saved_lines = _normalized_diff_lines(saved)
        draft_lines = _normalized_diff_lines(draft)

        sm = difflib.SequenceMatcher(None, saved_lines, draft_lines)

        # Populate left (saved) with removals highlighted
        self.left_edit.clear()
        cursor_left = self.left_edit.textCursor()

        # Populate right (draft) with additions highlighted
        self.right_edit.clear()
        cursor_right = self.right_edit.textCursor()

        fmt_normal = QTextCharFormat()
        fmt_removed = QTextCharFormat()
        fmt_removed.setBackground(QColor("#4d2020"))
        fmt_removed.setForeground(QColor("#fca5a5"))
        fmt_added = QTextCharFormat()
        fmt_added.setBackground(QColor("#1a3a1a"))
        fmt_added.setForeground(QColor("#86efac"))
        fmt_context = QTextCharFormat()
        fmt_context.setForeground(QColor("#94a3b8"))

        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for line in saved_lines[i1:i2]:
                    cursor_left.insertText(line, fmt_normal)
                    cursor_right.insertText(line, fmt_normal)
            elif tag == "delete":
                for line in saved_lines[i1:i2]:
                    cursor_left.insertText(line, fmt_removed)
            elif tag == "insert":
                for line in draft_lines[j1:j2]:
                    cursor_right.insertText(line, fmt_added)
            elif tag == "replace":
                for line in saved_lines[i1:i2]:
                    cursor_left.insertText(line, fmt_removed)
                for line in draft_lines[j1:j2]:
                    cursor_right.insertText(line, fmt_added)

        self.left_edit.moveCursor(QTextCursor.MoveOperation.Start)
        self.right_edit.moveCursor(QTextCursor.MoveOperation.Start)


def _make_panel(label, text_edit):
    from PySide6.QtWidgets import QWidget
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(label)
    layout.addWidget(text_edit, 1)
    return w


def _normalized_diff_lines(text: str) -> list[str]:
    return [f"{line.rstrip()}\n" for line in (text or "").splitlines()]
