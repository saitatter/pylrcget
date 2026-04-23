from __future__ import annotations

from collections import deque
import html
import logging
import os

from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.spacing import SPACE_1, SPACE_2, set_layout_spacing
from ui.theme_tokens import STYLE_TOKENS


class _LogBridge(QObject):
    messageReady = Signal(str, str)


class QtLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.bridge = _LogBridge()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            rendered = self.format(record)
            self.bridge.messageReady.emit(record.levelname, rendered)
        except Exception:
            self.handleError(record)


class LogPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("LogPanel")
        self._max_entries = 1000
        self._entries: deque[tuple[str, str]] = deque(maxlen=self._max_entries)
        self._log_path: str = ""

        root = QVBoxLayout(self)
        set_layout_spacing(root, margins=(SPACE_2, SPACE_2, SPACE_2, SPACE_2), spacing=SPACE_2)

        header = QHBoxLayout()
        set_layout_spacing(header, spacing=SPACE_2)

        title = QLabel("Logs")
        title.setObjectName("LogPanelTitle")
        header.addWidget(title)

        self.level_filter = QComboBox()
        self.level_filter.setObjectName("LogPanelFilter")
        self.level_filter.addItem("All", "ALL")
        self.level_filter.addItem("INFO", "INFO")
        self.level_filter.addItem("WARNING", "WARNING")
        self.level_filter.addItem("ERROR", "ERROR")
        self.level_filter.currentIndexChanged.connect(self._refresh_output)
        header.addWidget(self.level_filter)

        header.addStretch(1)

        self.btn_copy = QPushButton("Copy")
        self.btn_copy.setObjectName("LogPanelCopy")
        self.btn_copy.clicked.connect(self.copy_visible_logs)
        header.addWidget(self.btn_copy)

        self.btn_save = QPushButton("Save")
        self.btn_save.setObjectName("LogPanelSave")
        self.btn_save.clicked.connect(self.save_visible_logs)
        header.addWidget(self.btn_save)

        self.btn_open_folder = QPushButton("Open Folder")
        self.btn_open_folder.setObjectName("LogPanelOpenFolder")
        self.btn_open_folder.clicked.connect(self.open_log_folder)
        self.btn_open_folder.setEnabled(False)
        header.addWidget(self.btn_open_folder)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setObjectName("LogPanelClear")
        self.btn_clear.clicked.connect(self.clear)
        header.addWidget(self.btn_clear)

        root.addLayout(header)

        self.output = QTextEdit()
        self.output.setObjectName("LogPanelOutput")
        self.output.setReadOnly(True)
        self.output.document().setMaximumBlockCount(self._max_entries)
        root.addWidget(self.output, 1)

    def set_log_file_path(self, path: str) -> None:
        self._log_path = path or ""
        self.btn_open_folder.setEnabled(bool(self._log_path))

    def clear(self) -> None:
        self._entries.clear()
        self.output.clear()

    def append_log(self, level: str, message: str) -> None:
        level = level.upper()
        selected = self.level_filter.currentData() or "ALL"
        needs_full_refresh = len(self._entries) == self._max_entries
        self._entries.append((level, message))
        if needs_full_refresh:
            self._refresh_output()
            return

        if self._matches_filter(level, selected):
            bar = self.output.verticalScrollBar()
            at_bottom = bar is None or bar.value() >= bar.maximum() - 2
            self.output.append(self._render_entry(level, message))
            if bar is not None and at_bottom:
                bar.setValue(bar.maximum())

    def copy_visible_logs(self) -> None:
        QApplication.clipboard().setText(self._visible_log_text())

    def save_visible_logs(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Logs",
            "pylrcget.log",
            "Log Files (*.log);;Text Files (*.txt);;All Files (*)",
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self._visible_log_text())

    def open_log_folder(self) -> None:
        if not self._log_path:
            return
        folder = os.path.dirname(self._log_path)
        if not folder:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _visible_log_text(self) -> str:
        selected = self.level_filter.currentData() or "ALL"
        lines: list[str] = []
        for level, message in self._entries:
            if self._matches_filter(level, selected):
                lines.append(message)
        return "\n".join(lines).rstrip() + ("\n" if lines else "")

    def _matches_filter(self, level: str, selected: str) -> bool:
        if selected == "ALL":
            return True
        if selected == "ERROR":
            return level in {"ERROR", "CRITICAL"}
        return level == selected

    def _refresh_output(self) -> None:
        selected = self.level_filter.currentData() or "ALL"
        lines: list[str] = []
        for level, message in self._entries:
            if self._matches_filter(level, selected):
                lines.append(self._render_entry(level, message))
        self.output.setHtml("".join(lines))
        bar = self.output.verticalScrollBar()
        if bar is not None:
            bar.setValue(bar.maximum())

    def _render_entry(self, level: str, message: str) -> str:
        palette = {
            "INFO": STYLE_TOKENS.get("color-info-border", "#93c5fd"),
            "WARNING": STYLE_TOKENS.get("color-warning-border", "#fbbf24"),
            "ERROR": STYLE_TOKENS.get("color-error-border", "#f87171"),
            "CRITICAL": STYLE_TOKENS.get("color-error-text", "#ef4444"),
        }
        color = palette.get(level.upper(), STYLE_TOKENS.get("color-text-soft", "#cbd5e1"))
        safe = html.escape(message)
        return f'<span style="color:{color}; white-space:pre-wrap;">{safe}</span>'
