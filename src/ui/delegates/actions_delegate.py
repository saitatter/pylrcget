# ui/actions_delegate.py
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QRect, Signal, QSize
from PySide6.QtGui import QCursor, QPainter
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionButton

from core.tracklist_models import DownloadState, TrackListRow
from ui.icon_loader import load_svg_icon


class ActionsDelegate(QStyledItemDelegate):
    downloadClicked = Signal(int)  # track_id
    refreshClicked = Signal(int)  # track_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._ui_scale = 1.0
        self._refresh_icon = None
        self._update_resources()

    def set_ui_scale(self, scale: float) -> None:
        self._ui_scale = max(0.85, min(1.5, float(scale or 1.0)))
        self._update_resources()

    def _update_resources(self) -> None:
        size = int(round(14 * self._ui_scale))
        self._refresh_icon = load_svg_icon("refresh-cw.svg", size, "#e5e7eb")

    def _button_rects(self, cell_rect: QRect) -> tuple[QRect, QRect]:
        refresh_w = int(round(28 * self._ui_scale))
        refresh_h = int(round(26 * self._ui_scale))
        download_w = int(round(90 * self._ui_scale))
        download_h = int(round(26 * self._ui_scale))
        gap = int(round(6 * self._ui_scale))
        margin = int(round(8 * self._ui_scale))
        download_rect = QRect(
            cell_rect.right() - download_w - margin,
            cell_rect.center().y() - download_h // 2,
            download_w,
            download_h,
        )
        refresh_rect = QRect(
            download_rect.left() - gap - refresh_w,
            cell_rect.center().y() - refresh_h // 2,
            refresh_w,
            refresh_h,
        )
        return refresh_rect, download_rect

    def paint(self, painter: QPainter, option, index) -> None:
        super().paint(painter, option, index)
        row_obj: TrackListRow | None = index.data(Qt.UserRole)
        state = getattr(row_obj, "download_state", DownloadState.IDLE) if row_obj else DownloadState.IDLE

        refresh_rect, download_rect = self._button_rects(option.rect)
        hover_pos = option.widget.mapFromGlobal(QCursor.pos()) if option.widget is not None else None
        hover_refresh = bool(hover_pos is not None and refresh_rect.contains(hover_pos))
        hover_download = bool(hover_pos is not None and download_rect.contains(hover_pos))

        refresh_opt = QStyleOptionButton()
        refresh_opt.rect = refresh_rect
        refresh_opt.icon = self._refresh_icon
        icon_size = int(round(14 * self._ui_scale))
        refresh_opt.iconSize = QSize(icon_size, icon_size)
        refresh_opt.state = QStyle.State_Enabled
        if hover_refresh:
            refresh_opt.state |= QStyle.State_MouseOver

        download_opt = QStyleOptionButton()
        download_opt.rect = download_rect
        download_opt.text = {
            DownloadState.LOADING: "Working...",
            DownloadState.SUCCESS: "Done",
            DownloadState.ERROR: "Retry",
        }.get(state, "Download")
        download_opt.state = QStyle.State_None if state == DownloadState.LOADING else QStyle.State_Enabled
        if hover_download and state != DownloadState.LOADING:
            download_opt.state |= QStyle.State_MouseOver
        QApplication.style().drawControl(QStyle.CE_PushButton, refresh_opt, painter)
        QApplication.style().drawControl(QStyle.CE_PushButton, download_opt, painter)

    def editorEvent(self, event, model, option, index) -> bool:
        del model
        if index.column() != 3:
            return False
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.LeftButton:
            row_obj: TrackListRow | None = index.data(Qt.UserRole)
            if not row_obj:
                return False
            if getattr(row_obj, "download_state", DownloadState.IDLE) == DownloadState.LOADING:
                # Disable both row action buttons while a download is in progress.
                return False

            refresh_rect, download_rect = self._button_rects(option.rect)
            if refresh_rect.contains(event.pos()):
                self.refreshClicked.emit(row_obj.track_id)
                return True
            if download_rect.contains(event.pos()):
                self.downloadClicked.emit(row_obj.track_id)
                return True
        return False
