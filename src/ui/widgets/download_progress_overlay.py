from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt, Signal
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
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DownloadOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.hide()

        self._active = False
        self._ok_count = 0
        self._fail_count = 0
        self._total = 0

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
        self._active = True
        self._ok_count = 0
        self._fail_count = 0
        self._total = max(0, int(total))
        self.title_label.setText(f"Downloading ({mode_label})")
        self.progress_bar.setRange(0, max(1, self._total))
        self.progress_bar.setValue(0)
        self.status_label.setText("Preparing download queue…")
        self.output.clear()
        self.stop_btn.setText("STOP")
        self.stop_btn.setEnabled(True)
        self.close_btn.setEnabled(True)
        self._refresh_summary()
        self.sync_to_parent()
        self.show()
        self.raise_()

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
            self.title_label.setText("Download Cancelled")
        else:
            self.title_label.setText("Download Complete")

    def _refresh_summary(self) -> None:
        self.ok_label.setText(f"{self._ok_count} DOWNLOADED")
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
            self._handle_cancel()
            return
        self.hide()
        self.dismissed.emit()
