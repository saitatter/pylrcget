from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtWidgets import QLabel, QWidget


@dataclass
class _HotkeyHint:
    widget: QWidget
    key: str
    badge: QLabel


class HotkeyHintManager(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hints: list[_HotkeyHint] = []
        self._visible = False

    @property
    def is_visible(self) -> bool:
        return self._visible

    def register(self, widget: QWidget, key: str) -> None:
        if not key:
            return
        badge = QLabel(key, widget)
        badge.setObjectName("HotkeyHintBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        badge.hide()
        widget.installEventFilter(self)
        self._hints.append(_HotkeyHint(widget=widget, key=key, badge=badge))
        self._position_badge(self._hints[-1])

    def set_visible(self, visible: bool) -> None:
        self._visible = bool(visible)
        for hint in self._hints:
            self._position_badge(hint)
            hint.badge.setVisible(self._visible and hint.widget.isVisible())
            hint.badge.raise_()

    def toggle(self) -> bool:
        self.set_visible(not self._visible)
        return self._visible

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Move,
            QEvent.Type.Show,
            QEvent.Type.Hide,
            QEvent.Type.EnabledChange,
        }:
            for hint in self._hints:
                if hint.widget is watched:
                    self._position_badge(hint)
                    hint.badge.setVisible(self._visible and hint.widget.isVisible())
                    break
        return super().eventFilter(watched, event)

    def _position_badge(self, hint: _HotkeyHint) -> None:
        hint.badge.adjustSize()
        size = hint.badge.sizeHint()
        width = max(size.width() + 10, 28)
        height = max(size.height() + 4, 18)
        margin = 4
        x = max(margin, hint.widget.width() - width - margin)
        y = margin
        hint.badge.setGeometry(x, y, width, height)
