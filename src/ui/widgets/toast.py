from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer, QEasingCurve, QPoint, QPropertyAnimation
from PySide6.QtWidgets import (
    QWidget,
    QFrame,
    QLabel,
    QHBoxLayout,
    QToolButton,
    QGraphicsOpacityEffect,
)

from ui.spacing import SPACE_2, SPACE_3, set_layout_spacing
from ui.style_loader import load_stylesheet
from ui.theme_tokens import STYLE_TOKENS, rgba


@dataclass(frozen=True)
class ToastData:
    message: str
    notify_type: str = "info"  # "info" | "success" | "warning" | "error"
    timeout_ms: int = 3000

def _colors(kind: str) -> tuple[str, str, str, str]:
    """
    Returns (bg, border, text, hover_bg).
    """
    kind = (kind or "info").lower()
    palette_mode = STYLE_TOKENS.get("palette-mode", "dark")
    hover_bg = rgba(STYLE_TOKENS.get("color-text-strong", "#ffffff"), 0.08 if palette_mode == "dark" else 0.06)

    if kind == "success":
        return (
            STYLE_TOKENS.get("color-success-bg", "#052e1a"),
            STYLE_TOKENS.get("color-success-border", "#16a34a"),
            STYLE_TOKENS.get("color-success-text", "#e5e7eb"),
            hover_bg,
        )
    if kind == "warning":
        return (
            STYLE_TOKENS.get("color-warning-bg", "#2a1a05"),
            STYLE_TOKENS.get("color-warning-border", "#f59e0b"),
            STYLE_TOKENS.get("color-warning-text", "#e5e7eb"),
            hover_bg,
        )
    if kind == "error":
        return (
            STYLE_TOKENS.get("color-error-bg", "#2a0a0a"),
            STYLE_TOKENS.get("color-error-border", "#ef4444"),
            STYLE_TOKENS.get("color-error-text", "#e5e7eb"),
            hover_bg,
        )
    return (
        STYLE_TOKENS.get("color-bg-control", "#0b1222"),
        STYLE_TOKENS.get("color-accent", "#38bdf8"),
        STYLE_TOKENS.get("color-text", "#e5e7eb"),
        hover_bg,
    )

class ToastWidget(QFrame):
    def __init__(self, data: ToastData, parent: QWidget, manager: "ToastManager"):
        super().__init__(parent)
        self.data = data
        self._manager = manager

        bg, border, text, hover_bg = _colors(data.notify_type)

        self.setObjectName("Toast")
        self.setStyleSheet(load_stylesheet("toast.qss", bg=bg, border=border, text=text, hover_bg=hover_bg))

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QHBoxLayout(self)
        set_layout_spacing(root, margins=(SPACE_3, SPACE_2, SPACE_3, SPACE_2), spacing=SPACE_2)

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

        self._anim_opacity: QPropertyAnimation | None = None
        self._anim_pos: QPropertyAnimation | None = None

    @property
    def message(self) -> str:
        return self.lbl.text().strip()

    def close_requested(self):
        # Let the manager handle the removal animation.
        self._manager._dismiss_toast(self)

    def update_message(self, message: str):
        self.data = ToastData(message=message, notify_type=self.data.notify_type, timeout_ms=self.data.timeout_ms)
        self.lbl.setText(message)
        self.adjustSize()

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
    Overlay widget that stacks toasts upward from the player/status area.
    Attach it to a QMainWindow (or any QWidget).
    """
    def __init__(self, host: QWidget):
        super().__init__(host)
        self.host = host
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        self._toasts: list[ToastWidget] = []
        self._status_toast: ToastWidget | None = None
        self._status_generation = 0
        self._bottom_anchor: QWidget | None = None
        self._margin = 14
        self._spacing = 10
        self._max_visible = 5

        self._reposition_timer = QTimer(self)
        self._reposition_timer.setSingleShot(True)
        self._reposition_timer.timeout.connect(self._layout_toasts)

        self.sync_to_parent()
        self.raise_()
        self.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_layout()

    def sync_to_parent(self) -> None:
        self.setGeometry(self.host.rect())
        self._schedule_layout()

    def set_bottom_anchor(self, widget: QWidget | None) -> None:
        self._bottom_anchor = widget
        self._schedule_layout()

    def show_toast(self, message: str, notify_type: str = "info", timeout_ms: int = 3000):
        message = str(message or "").strip()
        if not message:
            return
        if self._status_toast is not None and self._status_toast.message == message:
            status_toast = self._status_toast
            self._status_toast = None
            if status_toast in self._toasts:
                self._toasts.remove(status_toast)
            status_toast.hide()
            status_toast.deleteLater()
        elif self._toast_with_message(message) is not None:
            return

        # Keep overlay always covering host
        self.setGeometry(self.host.rect())
        self.raise_()

        data = ToastData(message=message, notify_type=notify_type, timeout_ms=timeout_ms)
        toast = ToastWidget(data, parent=self.host, manager=self)
        self._set_toast_width(toast)
        toast.raise_()

        insert_at = 1 if self._status_toast in self._toasts else 0
        self._toasts.insert(insert_at, toast)

        # Enforce max visible: dismiss oldest
        while len(self._toasts) > self._max_visible:
            old = self._toasts.pop()
            if old is self._status_toast:
                self._status_toast = None
            old.hide()
            old.deleteLater()

        self._layout_toasts(animate_new=toast)

        # Auto dismiss
        QTimer.singleShot(max(500, int(timeout_ms)), lambda: self._dismiss_toast(toast))

    def show_status(self, message: str, timeout_ms: int | None = None) -> None:
        message = str(message or "").strip()
        if not message:
            self.clear_status()
            return
        if self._toast_with_message(message, exclude_status=True) is not None:
            return

        self.setGeometry(self.host.rect())
        self.raise_()
        self._status_generation += 1
        generation = self._status_generation

        if self._status_toast is None or self._status_toast not in self._toasts:
            data = ToastData(message=message, notify_type="info", timeout_ms=int(timeout_ms or 0))
            self._status_toast = ToastWidget(data, parent=self.host, manager=self)
            self._set_toast_width(self._status_toast)
            self._status_toast.raise_()
            self._toasts.insert(0, self._status_toast)
            self._layout_toasts(animate_new=self._status_toast)
        else:
            self._status_toast.update_message(message)
            self._set_toast_width(self._status_toast)
            self._layout_toasts()

        if timeout_ms is not None:
            QTimer.singleShot(
                max(500, int(timeout_ms)),
                lambda gen=generation: self.clear_status() if gen == self._status_generation else None,
            )

    def clear_status(self) -> None:
        self._status_generation += 1
        if self._status_toast is None:
            return
        toast = self._status_toast
        self._status_toast = None
        self._dismiss_toast(toast)

    def _dismiss_toast(self, toast: ToastWidget):
        if toast not in self._toasts:
            return
        if toast is self._status_toast:
            self._status_toast = None

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
        self.setGeometry(self.host.rect())

        x = self._margin
        y_bottom = self._bottom_limit()

        for t in self._toasts:
            t.adjustSize()
            self._set_toast_width(t)
            h = t.sizeHint().height()
            t.setFixedHeight(h)

            end_pos = QPoint(x, y_bottom - h)
            y_bottom -= h + self._spacing

            if t is animate_new:
                start_pos = end_pos + QPoint(0, -12)
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

    def _set_toast_width(self, toast: ToastWidget) -> None:
        toast.setFixedWidth(min(420, max(260, self.width() // 3)))

    def _bottom_limit(self) -> int:
        if self._bottom_anchor is not None and self._bottom_anchor.isVisible():
            return max(self._margin, self._bottom_anchor.y() - self._spacing)
        return max(self._margin, self.height() - self._margin)

    def _toast_with_message(self, message: str, *, exclude_status: bool = False) -> ToastWidget | None:
        for toast in self._toasts:
            if exclude_status and toast is self._status_toast:
                continue
            if toast.message == message:
                return toast
        return None
