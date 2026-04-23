from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import List, Optional

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QWidget, QStackedWidget
)
import re

from lrclib import LrcLibAPI
from lrclib.exceptions import APIError, IncorrectPublishTokenError, RateLimitError, ServerError

from ui.spacing import SPACE_2, SPACE_3, SPACE_4, set_layout_spacing

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class LintProblem:
    line: int
    severity: str  # "error" | "warning"
    message: str


_LRC_TS_RE = re.compile(r"\[\d{1,3}:\d{2}[.:]\d{2,3}\]")


def lint_lyrics(text: str, *, is_synced: bool) -> list[LintProblem]:
    """Validate lyrics text before publishing to LRCLIB."""
    problems: list[LintProblem] = []
    lines = text.splitlines()
    content_lines = [l for l in lines if l.strip()]

    if not content_lines:
        problems.append(LintProblem(line=1, severity="error", message="Lyrics are empty."))
        return problems

    if len(content_lines) < 2:
        problems.append(LintProblem(line=1, severity="warning", message="Very short lyrics (fewer than 2 lines)."))

    if is_synced:
        timestamps: list[tuple[int, int]] = []  # (line_num, ms)
        for i, raw in enumerate(lines, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            # skip metadata tags
            if re.match(r"^\[(ar|ti|al|by|offset|au):", stripped):
                continue
            matches = list(_LRC_TS_RE.finditer(stripped))
            if not matches:
                problems.append(LintProblem(line=i, severity="error", message="Line has no timestamp."))
                continue
            for m in matches:
                ts_text = m.group(0)[1:-1]  # strip [ ]
                parts = re.split(r"[:.]", ts_text)
                if len(parts) >= 3:
                    mins = int(parts[0])
                    secs = int(parts[1])
                    frac = parts[2]
                    if len(frac) == 2:
                        ms = int(frac) * 10
                    else:
                        ms = int(frac)
                    total_ms = mins * 60000 + secs * 1000 + ms
                    timestamps.append((i, total_ms))

        # Check ordering
        for j in range(1, len(timestamps)):
            prev_line, prev_ms = timestamps[j - 1]
            cur_line, cur_ms = timestamps[j]
            if cur_ms < prev_ms:
                problems.append(LintProblem(
                    line=cur_line,
                    severity="warning",
                    message=f"Timestamp is out of order (earlier than line {prev_line}).",
                ))
                break  # one warning is enough

        # Check duplicates
        seen_ms: dict[int, int] = {}
        for line_num, ms in timestamps:
            if ms in seen_ms:
                problems.append(LintProblem(
                    line=line_num,
                    severity="warning",
                    message=f"Duplicate timestamp (same as line {seen_ms[ms]}).",
                ))
            else:
                seen_ms[ms] = line_num

    return problems


@dataclass(frozen=True)
class PublishProgress:
    requestChallenge: str = "Pending"
    solveChallenge: str = "Pending"
    publishLyrics: str = "Pending"


class PublishWorker(QThread):
    progress = Signal(object)     # PublishProgress
    finished = Signal(bool, str)  # ok, message

    def __init__(self, payload: dict, lrclib_instance: str, parent=None):
        super().__init__(parent)
        self.payload = payload
        self.lrclib_instance = lrclib_instance

    def run(self):
        max_retries = 3
        backoff_s = 0.5

        for attempt in range(1, max_retries + 1):
            try:
                api = LrcLibAPI(user_agent="pylrcget", base_url=self.lrclib_instance)

                self.progress.emit(PublishProgress("In progress...", "Pending", "Pending"))
                self.progress.emit(PublishProgress("Done", "Pending", "Pending"))

                self.progress.emit(PublishProgress("Done", "In progress...", "Pending"))
                publish_token = api._obtain_publish_token()
                self.progress.emit(PublishProgress("Done", "Done", "Pending"))

                self.progress.emit(PublishProgress("Done", "Done", "In progress..."))
                try:
                    api.publish_lyrics(
                        track_name=self.payload["title"],
                        artist_name=self.payload["artistName"],
                        album_name=self.payload["albumName"],
                        duration=int(self.payload["duration"]),
                        plain_lyrics=self.payload.get("plainLyrics") or None,
                        synced_lyrics=self.payload.get("syncedLyrics") or None,
                        publish_token=publish_token,
                    )
                except json.JSONDecodeError:
                    pass  # LRCLIB returns empty 200 on success
                self.progress.emit(PublishProgress("Done", "Done", "Done"))

                self.finished.emit(True, "Lyrics were published successfully.")
                return
            except IncorrectPublishTokenError:
                logger.exception("Publish token rejected by LRCLIB")
                self.finished.emit(False, "Publish token was rejected. Try again.")
                return
            except (RateLimitError, ServerError) as e:
                if attempt < max_retries:
                    logger.warning(
                        "Publish attempt %d/%d failed (%s), retrying in %.1fs...",
                        attempt, max_retries, type(e).__name__, backoff_s,
                    )
                    self.progress.emit(PublishProgress("Done", "Done", f"Retrying in {backoff_s:.0f}s..."))
                    time.sleep(backoff_s)
                    backoff_s *= 2
                    continue
                logger.warning("Publish failed after %d attempts: %s", max_retries, e)
                self.finished.emit(False, f"Publish failed after {max_retries} attempts: {e}")
                return
            except APIError as e:
                logger.exception("LRCLIB API error during publish")
                self.finished.emit(False, f"LRCLIB error: {e}")
                return
            except Exception as e:
                logger.exception("Unexpected error during publish")
                self.finished.emit(False, f"Publish failed: {e}")
                return


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
        lrclib_instance: str = "https://lrclib.net",
        parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle("Publish Lyrics")
        self.setModal(True)
        self.setObjectName("PublishLyricsDialog")

        self._is_publishing = False
        self.publish_result: bool | None = None
        self._lint = lint_result or []
        self._is_synced = is_synced
        self._lrclib_instance = lrclib_instance

        self.resize(650, 420)

        root = QVBoxLayout(self)
        set_layout_spacing(root, margins=SPACE_4, spacing=SPACE_3)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        # --- page 0: lint table
        lint_page = QWidget()
        lint_layout = QVBoxLayout(lint_page)
        set_layout_spacing(lint_layout, spacing=SPACE_2)

        self.lint_header = QLabel("Fix the following issues before publishing")
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
        set_layout_spacing(pub_layout, spacing=SPACE_3)
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
        set_layout_spacing(footer, spacing=SPACE_2)
        footer.addStretch(1)

        self.btn_primary = QPushButton()
        self.btn_secondary = QPushButton("Cancel")

        self.btn_primary.clicked.connect(self._on_primary)
        self.btn_secondary.clicked.connect(self._on_secondary)

        footer.addWidget(self.btn_primary)
        footer.addWidget(self.btn_secondary)

        root.addLayout(footer)

        # decide which page
        errors = [p for p in self._lint if p.severity == "error"]
        warnings = [p for p in self._lint if p.severity != "error"]
        if errors:
            self._populate_lint(self._lint)
            self.stack.setCurrentIndex(0)
            self.btn_primary.setText("Close")
            self.btn_secondary.hide()
        elif warnings:
            self._populate_lint(warnings)
            self.lint_header.setText("Warnings found — you can still publish")
            self.stack.setCurrentIndex(0)
            self.btn_primary.setText("Publish Anyway")
            self._warnings_only = True
            self.btn_secondary.show()
        else:
            self.stack.setCurrentIndex(1)
            kind = "synchronized" if is_synced else "unsynchronized"
            self.info_label.setText(
                f"Publish the {kind} lyrics for <b>{title} - {artist_name}</b> to the current LRCLIB instance?"
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
        if self._lint and not getattr(self, '_warnings_only', False):
            self.reject()
            return
        if getattr(self, '_warnings_only', False) and not self._is_publishing:
            self._warnings_only = False
            self._lint = []
            kind = "synchronized" if self._is_synced else "unsynchronized"
            self.info_label.setText(
                f"Publish the {kind} lyrics for <b>{self._payload['title']} - {self._payload['artistName']}</b> to the current LRCLIB instance?"
            )
            self.stack.setCurrentIndex(1)
            self.btn_primary.setText("Publish Now")
            return
        if not self._is_publishing:
            self._start_publish()

    def _on_secondary(self):
        if not self._is_publishing:
            self.reject()

    def _start_publish(self):
        self._is_publishing = True
        self.publish_result = None
        self.btn_primary.setEnabled(False)
        self.btn_secondary.setEnabled(False)
        self._set_primary_feedback("loading", "Publishing...")

        # update text like Vue "Publishing..."
        kind = "synchronized" if self._is_synced else "unsynchronized"
        self.info_label.setText(
            f"Publishing the {kind} lyrics for "
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

        self.worker = PublishWorker(payload, self._lrclib_instance, self)
        self.worker.progress.connect(self._set_progress)
        self.worker.finished.connect(self._publish_done)
        self.worker.start()

    def _publish_done(self, ok: bool, msg: str):
        self._is_publishing = False
        if ok:
            self.publish_result = True
            self._set_primary_feedback("success", "Published")
            self.info_label.setText(f"<b>{msg}</b>")
            QTimer.singleShot(1000, self.accept)
            return

        self.publish_result = False
        self._set_primary_feedback("error", "Retry Publish")
        self.info_label.setText(f"<b>Publishing failed.</b><br>{msg}")
        self.btn_primary.setEnabled(True)
        self.btn_secondary.setEnabled(True)

    def _set_primary_feedback(self, state: str, text: str):
        self.btn_primary.setText(text)
        self.btn_primary.setProperty("actionState", state if state != "idle" else "")
        self.btn_primary.style().unpolish(self.btn_primary)
        self.btn_primary.style().polish(self.btn_primary)
        self.btn_primary.update()
        self.btn_primary.setEnabled(state != "loading")
