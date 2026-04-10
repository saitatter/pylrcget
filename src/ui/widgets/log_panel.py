from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from ui.spacing import SPACE_1, SPACE_2, set_layout_spacing


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

        root = QVBoxLayout(self)
        set_layout_spacing(root, margins=(SPACE_2, SPACE_2, SPACE_2, SPACE_2), spacing=SPACE_2)

        header = QHBoxLayout()
        set_layout_spacing(header, spacing=SPACE_2)

        title = QLabel("Logs")
        title.setObjectName("LogPanelTitle")
        header.addWidget(title)
        header.addStretch(1)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setObjectName("LogPanelClear")
        self.btn_clear.clicked.connect(self.clear)
        header.addWidget(self.btn_clear)

        root.addLayout(header)

        self.output = QPlainTextEdit()
        self.output.setObjectName("LogPanelOutput")
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(2000)
        root.addWidget(self.output, 1)

    def clear(self) -> None:
        self.output.clear()

    def append_log(self, level: str, message: str) -> None:
        self.output.appendPlainText(message)
        bar = self.output.verticalScrollBar()
        if bar is not None:
            bar.setValue(bar.maximum())
