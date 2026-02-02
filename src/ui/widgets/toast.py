from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QEasingCurve, QPoint, QPropertyAnimation
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget,
    QFrame,
    QLabel,
    QHBoxLayout,
    QVBoxLayout,
    QToolButton,
    QGraphicsOpacityEffect,
)


@dataclass(frozen=True)
class ToastData:
    message: str
    notify_type: str = "info"  # "info" | "success" | "warning" | "error"
    timeout_ms: int = 3000


def _colors(kind: str) -> tuple[str, str, str]:
    """
    Returns (bg, border, text).
    """
    kind = (kind or "info").lower()
    if kind == "success":
        return "#052e1a", "#16a34a", "#e5e7eb"
    if kind == "warning":
        return "#2a1a05", "#f59e0b", "#e5e7eb"
    if kind == "error":
        return "#2a0a0a", "#ef4444", "#e5e7eb"
    return "#0b1222", "#38bdf8", "#e5e7eb"


class ToastWidget(QFrame):
    def __init__(self, data: ToastData, parent: QWidget):
        super().__init__(parent)
        self.data = data

        bg, border, text = _colors(data.notify_type)

        self.setObjectName("Toast")
        self.setStyleSheet(f"""
        QFrame#Toast {{
            background: {bg};
            border: 1px solid {border};
            border-radius: 14px;
        }}
        QLabel {{
            color: {text};
            font-size: 12px;
        }}
        QToolButton {{
            border: none;
            background: transparent;
            color: {text};
            padding: 2px 6px;
        }}
        QToolButton:hover {{
            background: rgba(255,255,255,0.06);
            border-radius: 8px;
        }}
        """)

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 10, 10, 10)
        root.setSpacing(10)

        self.lbl = QLabel(data.message)
        self.lbl.setWordWrap(True)

        self.btn_close = QToolButton()
        self.btn_close.setText("✕")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(self.close_requested)

        root.addWidget(self.lbl, 1)
        root.addWidget(self.btn_close, 0, Qt.AlignmentFlag.AlignTop)

        # Fade effect
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)

        self._anim_opacity: Optional[QPropertyAnimation] = None
        self._anim_pos: Optional[QPropertyAnimation] = None

    def close_requested(self):
        # Let the manager handle the removal animation.
        self.parent()._dismiss_toast(self)  # type: ignore[attr-defined]

    def play_in(self, start_pos: QPoint, end_pos: QPoint):
        self.move(start_pos)

        self._anim_pos = QPropertyAnimation(self, b"pos", self)
        self._anim_pos.setDuration(180)
        self._anim_pos.setStartValue(start_pos)
        self._anim_pos.setEndValue(end_pos)
        self._anim_pos.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._anim_opacity = QPropertyAnimation(self._opacity, b"opacity", self)
        self._anim_opacity.setDuration(180)
        self._anim_opacity.setStartValue(0.0)
        self._anim_opacity.setEndValue(1.0)
        self._anim_opacity.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.show()
        self._anim_pos.start()
        self._anim_opacity.start()

    def play_out(self, on_done):
        anim1 = QPropertyAnimation(self._opacity, b"opacity", self)
        anim1.setDuration(180)
        anim1.setStartValue(self._opacity.opacity())
        anim1.setEndValue(0.0)
        anim1.setEasingCurve(QEasingCurve.Type.InCubic)

        # Slide slightly up while fading out
        anim2 = QPropertyAnimation(self, b"pos", self)
        anim2.setDuration(180)
        anim2.setStartValue(self.pos())
        anim2.setEndValue(self.pos() + QPoint(0, -6))
        anim2.setEasingCurve(QEasingCurve.Type.InCubic)

        def _done():
            on_done()
        anim1.finished.connect(_done)

        anim2.start()
        anim1.start()


class ToastManager(QWidget):
    """
    Overlay widget that stacks toasts from top -> bottom (like phone notifications).
    Attach it to a QMainWindow (or any QWidget).
    """
    def __init__(self, host: QWidget):
        super().__init__(host)
        self.host = host
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        self._toasts: list[ToastWidget] = []
        self._margin = 14
        self._spacing = 10
        self._max_visible = 5

        self._reposition_timer = QTimer(self)
        self._reposition_timer.setSingleShot(True)
        self._reposition_timer.timeout.connect(self._layout_toasts)

        self.raise_()
        self.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_layout()

    def show_toast(self, message: str, notify_type: str = "info", timeout_ms: int = 3000):
        # Keep overlay always covering host
        self.setGeometry(self.host.rect())
        self.raise_()

        data = ToastData(message=message, notify_type=notify_type, timeout_ms=timeout_ms)
        toast = ToastWidget(data, parent=self)
        toast.setFixedWidth(min(420, max(260, self.width() // 2)))

        # Insert newest at top
        self._toasts.insert(0, toast)

        # Enforce max visible: dismiss oldest
        while len(self._toasts) > self._max_visible:
            old = self._toasts.pop()
            old.hide()
            old.deleteLater()

        self._layout_toasts(animate_new=toast)

        # Auto dismiss
        QTimer.singleShot(max(500, int(timeout_ms)), lambda: self._dismiss_toast(toast))

    def _dismiss_toast(self, toast: ToastWidget):
        if toast not in self._toasts:
            return

        def remove():
            if toast in self._toasts:
                self._toasts.remove(toast)
            toast.hide()
            toast.deleteLater()
            self._layout_toasts()

        toast.play_out(remove)

    def _schedule_layout(self):
        # Coalesce rapid resize / multiple toasts
        self._reposition_timer.start(0)

    def _layout_toasts(self, animate_new: ToastWidget | None = None):
        # Top-right stack
        self.setGeometry(self.host.rect())

        x_right = self.width() - self._margin
        y = self._margin

        for i, t in enumerate(self._toasts):
            t.adjustSize()
            w = t.width()
            h = t.sizeHint().height()
            t.setFixedHeight(h)

            end_pos = QPoint(x_right - w, y)
            y += h + self._spacing

            if t is animate_new:
                start_pos = end_pos + QPoint(0, -12)  # slide down into place
                t.play_in(start_pos=start_pos, end_pos=end_pos)
            else:
                # Smooth reposition (optional)
                if t.isVisible():
                    anim = QPropertyAnimation(t, b"pos", t)
                    anim.setDuration(160)
                    anim.setStartValue(t.pos())
                    anim.setEndValue(end_pos)
                    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                    anim.start()
                else:
                    t.move(end_pos)
                    t.show()

        self.raise_()
