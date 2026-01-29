from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QWidget, QStackedWidget
)
import re

@dataclass(frozen=True)
class LintProblem:
    line: int
    severity: str  # "error" (you can extend later)
    message: str


@dataclass(frozen=True)
class PublishProgress:
    requestChallenge: str = "Pending"
    solveChallenge: str = "Pending"
    publishLyrics: str = "Pending"


class PublishWorker(QThread):
    progress = Signal(object)     # PublishProgress
    finished = Signal(bool, str)  # ok, message

    def __init__(self, payload: dict, parent=None):
        super().__init__(parent)
        self.payload = payload

    def run(self):
        try:
            # TODO: implement real LRCLIB publishing
            # For now we simulate the 3 phases.
            self.progress.emit(PublishProgress("Done", "Pending", "Pending"))
            self.msleep(400)
            self.progress.emit(PublishProgress("Done", "Done", "Pending"))
            self.msleep(400)
            self.progress.emit(PublishProgress("Done", "Done", "Done"))
            self.msleep(300)

            self.finished.emit(True, "Published successfully (stub).")
        except Exception as e:
            self.finished.emit(False, f"Publish failed: {e}")


class PublishLyricsDialog(QDialog):
    """
    PySide equivalent for Vue BaseModal publishing dialogs.
    Shows either:
      - lint result table (if lint problems exist), or
      - confirmation + progress table
    """
    def __init__(
        self,
        title: str,
        artist_name: str,
        album_name: str,
        duration_s: float,
        lyrics_text: str,
        is_synced: bool,
        lint_result: Optional[List[LintProblem]] = None,
        parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle("Publish Lyrics")
        self.setModal(True)

        self._is_publishing = False
        self._lint = lint_result or []
        self._is_synced = is_synced

        self.resize(650, 420)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        # --- page 0: lint table
        lint_page = QWidget()
        lint_layout = QVBoxLayout(lint_page)
        lint_layout.setSpacing(8)

        self.lint_header = QLabel("Please fix the following problem(s) before publishing")
        lint_layout.addWidget(self.lint_header)

        self.lint_table = QTableWidget(0, 3)
        self.lint_table.setHorizontalHeaderLabels(["Line", "Severity", "Message"])
        self.lint_table.horizontalHeader().setStretchLastSection(True)
        self.lint_table.verticalHeader().setVisible(False)
        self.lint_table.setEditTriggers(self.lint_table.EditTrigger.NoEditTriggers)
        self.lint_table.setSelectionMode(self.lint_table.SelectionMode.NoSelection)
        lint_layout.addWidget(self.lint_table, 1)

        self.stack.addWidget(lint_page)

        # --- page 1: confirm/progress
        pub_page = QWidget()
        pub_layout = QVBoxLayout(pub_page)
        pub_layout.setSpacing(12)
        pub_layout.setAlignment(Qt.AlignTop)

        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        pub_layout.addWidget(self.info_label)

        self.progress_table = QTableWidget(3, 2)
        self.progress_table.setHorizontalHeaderLabels(["Step", "Status"])
        self.progress_table.verticalHeader().setVisible(False)
        self.progress_table.horizontalHeader().setStretchLastSection(True)
        self.progress_table.setEditTriggers(self.progress_table.EditTrigger.NoEditTriggers)
        self.progress_table.setSelectionMode(self.progress_table.SelectionMode.NoSelection)

        self.progress_table.setItem(0, 0, QTableWidgetItem("Request challenge..."))
        self.progress_table.setItem(1, 0, QTableWidgetItem("Solve challenge..."))
        self.progress_table.setItem(2, 0, QTableWidgetItem("Publish lyrics..."))
        self._set_progress(PublishProgress())

        pub_layout.addWidget(self.progress_table)

        self.stack.addWidget(pub_page)

        # --- footer buttons
        footer = QHBoxLayout()
        footer.addStretch(1)

        self.btn_primary = QPushButton()
        self.btn_secondary = QPushButton("Cancel")

        self.btn_primary.clicked.connect(self._on_primary)
        self.btn_secondary.clicked.connect(self._on_secondary)

        footer.addWidget(self.btn_primary)
        footer.addWidget(self.btn_secondary)

        root.addLayout(footer)

        # decide which page
        if self._lint:
            self._populate_lint(self._lint)
            self.stack.setCurrentIndex(0)
            self.btn_primary.setText("Close")
            self.btn_secondary.hide()
        else:
            self.stack.setCurrentIndex(1)
            kind = "synchronized" if is_synced else "unsynchronized"
            self.info_label.setText(
                f"Do you want to publish your {kind} lyrics of the song "
                f"<b>{title} - {artist_name}</b> to your current LRCLIB instance?"
            )
            self.btn_primary.setText("Publish Now")
            self.btn_secondary.show()

        # store payload pieces
        self._payload = {
            "title": title,
            "artistName": artist_name,
            "albumName": album_name,
            "duration": float(duration_s),
            "lyrics": lyrics_text,
            "isSynced": bool(is_synced),
        }

    def _populate_lint(self, problems: List[LintProblem]):
        self.lint_table.setRowCount(len(problems))
        for r, p in enumerate(problems):
            self.lint_table.setItem(r, 0, QTableWidgetItem(str(p.line)))
            self.lint_table.setItem(r, 1, QTableWidgetItem(p.severity))
            self.lint_table.setItem(r, 2, QTableWidgetItem(p.message))

    def _set_progress(self, prog: PublishProgress):
        self.progress_table.setItem(0, 1, QTableWidgetItem(prog.requestChallenge))
        self.progress_table.setItem(1, 1, QTableWidgetItem(prog.solveChallenge))
        self.progress_table.setItem(2, 1, QTableWidgetItem(prog.publishLyrics))

    def _on_primary(self):
        if self._lint:
            self.reject()
            return
        if not self._is_publishing:
            self._start_publish()

    def _on_secondary(self):
        if not self._is_publishing:
            self.reject()

    def _start_publish(self):
        self._is_publishing = True
        self.btn_primary.setEnabled(False)
        self.btn_secondary.setEnabled(False)

        # update text like Vue "Publishing..."
        kind = "synchronized" if self._is_synced else "unsynchronized"
        self.info_label.setText(
            f"Publishing your {kind} lyrics of the song "
            f"<b>{self._payload['title']} - {self._payload['artistName']}</b>..."
        )
        self._set_progress(PublishProgress())

        # build final payload like Vue does
        lyrics = self._payload["lyrics"] or ""
        if self._payload["isSynced"]:
            # plain = strip timestamps
            plain = re.sub(r"^\[(.*)\]\s*", "", lyrics, flags=re.MULTILINE)
            synced = lyrics
        else:
            plain = lyrics
            synced = ""

        payload = {
            "title": self._payload["title"],
            "albumName": self._payload["albumName"],
            "artistName": self._payload["artistName"],
            "duration": self._payload["duration"],
            "plainLyrics": plain,
            "syncedLyrics": synced,
        }

        self.worker = PublishWorker(payload, self)
        self.worker.progress.connect(self._set_progress)
        self.worker.finished.connect(self._publish_done)
        self.worker.start()

    def _publish_done(self, ok: bool, msg: str):
        self._is_publishing = False
        # close dialog like Vue finally { close() }
        self.accept() if ok else self.reject()
