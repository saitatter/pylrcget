from __future__ import annotations

from html import escape

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.spacing import SPACE_1, SPACE_2, SPACE_3, set_layout_spacing
from ui.theme_tokens import STYLE_TOKENS


class DownloadProgressOverlay(QWidget):
    cancelRequested = Signal()
    retryFailedRequested = Signal()
    dismissed = Signal()
    minimized = Signal()           # overlay hidden while operation still running
    activeChanged = Signal(bool)   # True = batch started, False = batch finished/cancelled

    def __init__(self, parent: QWidget | None = None, *, verb: str = "Download"):
        super().__init__(parent)
        self.setObjectName("DownloadOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.hide()

        self._verb = verb  # "Download" or "Publish"
        self._verb_ing = f"{verb.rstrip('e')}ing" if verb.endswith('e') else f"{verb}ing"
        self._verb_ed = f"{verb.rstrip('e')}ed" if verb.endswith('e') else f"{verb}ed"
        self._active = False
        self._ok_count = 0
        self._fail_count = 0
        self._total = 0
        self._auto_close_timer = QTimer(self)
        self._auto_close_timer.setSingleShot(True)
        self._auto_close_timer.timeout.connect(self._dismiss_overlay)

        root = QVBoxLayout(self)
        set_layout_spacing(root, margins=(SPACE_3, SPACE_3, SPACE_3, SPACE_3), spacing=0)
        root.addStretch(1)

        card_row = QHBoxLayout()
        set_layout_spacing(card_row, spacing=0)
        card_row.addStretch(1)

        self.card = QFrame()
        self.card.setObjectName("DownloadOverlayCard")
        card_layout = QVBoxLayout(self.card)
        set_layout_spacing(card_layout, margins=(SPACE_3, SPACE_3, SPACE_3, SPACE_3), spacing=SPACE_2)

        title_row = QHBoxLayout()
        set_layout_spacing(title_row, spacing=SPACE_2)
        self.title_label = QLabel("Downloading")
        self.title_label.setObjectName("DownloadOverlayTitle")
        title_row.addWidget(self.title_label)
        title_row.addStretch(1)

        self.close_btn = QToolButton()
        self.close_btn.setObjectName("DownloadOverlayClose")
        self.close_btn.setText("×")
        self.close_btn.clicked.connect(self._handle_close)
        title_row.addWidget(self.close_btn)
        card_layout.addLayout(title_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("DownloadOverlayProgress")
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        card_layout.addWidget(self.progress_bar)

        summary_row = QHBoxLayout()
        set_layout_spacing(summary_row, spacing=SPACE_2)
        summary_row.addStretch(1)
        self.ok_label = QLabel("0 DOWNLOADED")
        self.ok_label.setObjectName("DownloadOverlaySummaryOk")
        self.fail_label = QLabel("0 FAILED")
        self.fail_label.setObjectName("DownloadOverlaySummaryFail")
        summary_row.addWidget(self.ok_label)
        summary_row.addWidget(self.fail_label)
        summary_row.addStretch(1)
        card_layout.addLayout(summary_row)

        self.status_label = QLabel("Preparing download queue…")
        self.status_label.setObjectName("DownloadOverlayStatus")
        self.status_label.setWordWrap(True)
        card_layout.addWidget(self.status_label)

        self.output = QTextEdit()
        self.output.setObjectName("DownloadOverlayLog")
        self.output.setReadOnly(True)
        self.output.document().setMaximumBlockCount(1500)
        card_layout.addWidget(self.output, 1)

        actions_row = QHBoxLayout()
        set_layout_spacing(actions_row, spacing=SPACE_2)
        actions_row.addStretch(1)
        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setObjectName("DownloadOverlayStop")
        self.stop_btn.clicked.connect(self._handle_cancel)
        self.retry_failed_btn = QPushButton("RETRY FAILED")
        self.retry_failed_btn.setObjectName("DownloadOverlayRetry")
        self.retry_failed_btn.hide()
        self.retry_failed_btn.clicked.connect(self.retryFailedRequested.emit)
        actions_row.addWidget(self.retry_failed_btn)
        actions_row.addWidget(self.stop_btn)
        actions_row.addStretch(1)
        card_layout.addLayout(actions_row)

        card_row.addWidget(self.card, 0)
        card_row.addStretch(1)
        root.addLayout(card_row)
        root.addStretch(1)

    def sync_to_parent(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())

    def start_batch(self, mode_label: str, total: int) -> None:
        self._auto_close_timer.stop()
        self._active = True
        self._ok_count = 0
        self._fail_count = 0
        self._total = max(0, int(total))
        self.title_label.setText(f"{self._verb_ing} ({mode_label})")
        self.progress_bar.setRange(0, max(1, self._total))
        self.progress_bar.setValue(0)
        self.status_label.setText(f"Preparing {self._verb.lower()} queue…")
        self.output.clear()
        self.stop_btn.setText("STOP")
        self.stop_btn.setEnabled(True)
        self.retry_failed_btn.hide()
        self.retry_failed_btn.setEnabled(False)
        self.close_btn.setEnabled(True)
        self._refresh_summary()
        self.sync_to_parent()
        self.show()
        self.raise_()
        self.activeChanged.emit(True)

    def update_progress(self, current: int, total: int, track_label: str, status: str) -> None:
        self._total = max(0, int(total))
        self.progress_bar.setRange(0, max(1, self._total))
        self.progress_bar.setValue(min(int(current), int(total)))
        label = (track_label or "").strip()
        if label:
            self.status_label.setText(f"{label}  •  {status}")
        else:
            self.status_label.setText(status)

    def append_result(self, track_label: str, message: str, ok: bool) -> None:
        if ok:
            self._ok_count += 1
            color = STYLE_TOKENS.get("color-success-border", "#15803d")
        else:
            self._fail_count += 1
            color = STYLE_TOKENS.get("color-error-border", "#b91c1c")
        self._refresh_summary()

        label = escape((track_label or "Track").strip())
        msg = escape((message or "").strip())
        self.output.append(
            f'<span style="color:{color};"><b>{label}</b>: {msg}</span>'
        )
        bar = self.output.verticalScrollBar()
        if bar is not None:
            bar.setValue(bar.maximum())

    def finish_batch(self, message: str, *, cancelled: bool = False) -> None:
        self._active = False
        self.status_label.setText(message)
        self.stop_btn.setEnabled(True)
        self.stop_btn.setText("CLOSE")
        if cancelled:
            self.title_label.setText(f"{self._verb} Cancelled")
        else:
            self.title_label.setText(f"{self._verb} Complete")
        self.activeChanged.emit(False)

    def show_retry_failed(self, count: int) -> None:
        count = max(0, int(count))
        if count <= 0:
            self.retry_failed_btn.hide()
            self.retry_failed_btn.setEnabled(False)
            return
        label = "RETRY FAILED" if count == 1 else f"RETRY {count} FAILED"
        self.retry_failed_btn.setText(label)
        self.retry_failed_btn.setEnabled(True)
        self.retry_failed_btn.show()

    def queue_auto_close(self, delay_ms: int) -> None:
        if self._active:
            return
        timeout = max(250, int(delay_ms))
        self._auto_close_timer.start(timeout)

    def _refresh_summary(self) -> None:
        self.ok_label.setText(f"{self._ok_count} {self._verb_ed.upper()}")
        self.fail_label.setText(f"{self._fail_count} FAILED")

    def _handle_cancel(self) -> None:
        if self._active:
            self.stop_btn.setEnabled(False)
            self.status_label.setText("Cancelling after the current track…")
            self.cancelRequested.emit()
            return
        self.hide()
        self.dismissed.emit()

    def _handle_close(self) -> None:
        if self._active:
            # Minimize — hide overlay but keep operation running
            self.hide()
            self.minimized.emit()
            return
        self._dismiss_overlay()

    @property
    def is_active(self) -> bool:
        return self._active

    def reopen(self) -> None:
        """Show the overlay again (e.g. from a header button)."""
        self.sync_to_parent()
        self.show()
        self.raise_()

    def _dismiss_overlay(self) -> None:
        self._auto_close_timer.stop()
        self.hide()
        self.dismissed.emit()
