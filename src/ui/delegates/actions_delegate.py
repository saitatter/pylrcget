# ui/actions_delegate.py
from __future__ import annotations
from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionButton, QApplication, QStyle

class ActionsDelegate(QStyledItemDelegate):
    downloadClicked = Signal(int)  # track_id

    def paint(self, painter: QPainter, option, index):
        super().paint(painter, option, index)

        rect = option.rect
        btn_w, btn_h = 90, 26
        btn_rect = QRect(rect.right() - btn_w - 8, rect.center().y() - btn_h // 2, btn_w, btn_h)

        opt = QStyleOptionButton()
        opt.rect = btn_rect
        opt.text = "Download"
        opt.state = QStyle.State_Enabled
        QApplication.style().drawControl(QStyle.CE_PushButton, opt, painter)

    def editorEvent(self, event, model, option, index):
        if index.column() != 3:
            return False
        if event.type() == event.MouseButtonRelease and event.button() == Qt.LeftButton:
            row_obj = index.data(Qt.UserRole)
            if not row_obj:
                return False

            rect = option.rect
            btn_w, btn_h = 90, 26
            btn_rect = QRect(rect.right() - btn_w - 8, rect.center().y() - btn_h // 2, btn_w, btn_h)

            if btn_rect.contains(event.pos()):
                self.downloadClicked.emit(row_obj.track_id)
                return True
        return False
