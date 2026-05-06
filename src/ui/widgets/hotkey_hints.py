from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QEvent, QPoint, Qt
from PySide6.QtGui import QFont
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
        badge_parent = widget.window() if widget.window() is not None else widget
        badge = QLabel(key, badge_parent)
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
        parent = hint.widget.window() if hint.widget.window() is not None else hint.widget
        if hint.badge.parentWidget() is not parent:
            hint.badge.setParent(parent)
        hint.badge.setText(self._badge_text(hint.widget, hint.key))
        hint.badge.setFont(self._badge_font(hint.widget, hint.badge))
        size = hint.badge.sizeHint()
        target_height = max(1, hint.widget.height())
        scale = max(0.72, min(1.0, target_height / 44.0))
        margin = max(2, int(4 * scale))
        min_width = int(18 * scale)
        if target_height < 34:
            max_width = max(12, hint.widget.width() - 2 * margin)
            width = min(max(int(size.width() + 4 * scale), min_width), max_width)
        else:
            width = max(int(size.width() + 4 * scale), min_width)
        height = max(int(size.height() + 4 * scale), int(16 * scale))

        if width > hint.widget.width():
            local_x = (hint.widget.width() - width) // 2
            local_y = -max(0, height - max(8, hint.widget.height() // 2))
        else:
            local_x = max(margin, hint.widget.width() - width - margin)
            local_y = margin
        if parent is hint.widget:
            origin = QPoint(local_x, local_y)
        else:
            origin = hint.widget.mapTo(parent, QPoint(local_x, local_y))
        hint.badge.setGeometry(origin.x(), origin.y(), width, height)

    @staticmethod
    def _badge_font(widget: QWidget, badge: QLabel) -> QFont:
        font = QFont(badge.font())
        target_height = max(1, widget.height())
        if target_height < 34:
            font.setPointSize(max(5, font.pointSize() - 3))
        elif target_height < 40:
            font.setPointSize(max(7, font.pointSize() - 1))
        return font

    @staticmethod
    def _badge_text(widget: QWidget, key: str) -> str:
        if widget.height() >= 34:
            return key
        compact_keys = {
            "Ctrl+Left": "C<",
            "Ctrl+Right": "C>",
            "Space": "Sp",
        }
        if key in compact_keys:
            return compact_keys[key]
        return (
            key.replace("Ctrl+", "C+")
            .replace("Alt+", "A+")
            .replace("Shift+", "S+")
        )
