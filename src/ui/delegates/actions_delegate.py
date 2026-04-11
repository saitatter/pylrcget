# ui/actions_delegate.py
from __future__ import annotations
from PySide6.QtCore import QEvent, Qt, QRect, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionButton, QApplication, QStyle
from core.tracklist_models import DownloadState

class ActionsDelegate(QStyledItemDelegate):
    downloadClicked = Signal(int)  # track_id

    def paint(self, painter: QPainter, option, index):
        super().paint(painter, option, index)
        row_obj = index.data(Qt.UserRole)
        state = getattr(row_obj, "download_state", DownloadState.IDLE) if row_obj else DownloadState.IDLE

        rect = option.rect
        btn_w, btn_h = 90, 26
        btn_rect = QRect(rect.right() - btn_w - 8, rect.center().y() - btn_h // 2, btn_w, btn_h)

        opt = QStyleOptionButton()
        opt.rect = btn_rect
        opt.text = {
            DownloadState.LOADING: "Working...",
            DownloadState.SUCCESS: "Done",
            DownloadState.ERROR: "Retry",
        }.get(state, "Download")
        opt.state = QStyle.State_None if state == DownloadState.LOADING else QStyle.State_Enabled
        if option.state & QStyle.State_MouseOver and state != DownloadState.LOADING:
            opt.state |= QStyle.State_MouseOver
        QApplication.style().drawControl(QStyle.CE_PushButton, opt, painter)

    def editorEvent(self, event, model, option, index):
        if index.column() != 3:
            return False
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.LeftButton:
            row_obj = index.data(Qt.UserRole)
            if not row_obj:
                return False
            if getattr(row_obj, "download_state", DownloadState.IDLE) == DownloadState.LOADING:
                return False

            rect = option.rect
            btn_w, btn_h = 90, 26
            btn_rect = QRect(rect.right() - btn_w - 8, rect.center().y() - btn_h // 2, btn_w, btn_h)

            if btn_rect.contains(event.pos()):
                self.downloadClicked.emit(row_obj.track_id)
                return True
        return False
