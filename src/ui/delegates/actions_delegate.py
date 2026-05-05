# ui/actions_delegate.py
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QRect, Signal, QSize
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionButton, QStyleOptionViewItem

from core.tracklist_models import DownloadState, TrackListRow
from ui.icon_loader import load_svg_icon
from ui.theme_tokens import STYLE_TOKENS


class ActionsDelegate(QStyledItemDelegate):
    downloadClicked = Signal(int)  # track_id
    refreshClicked = Signal(int)  # track_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._ui_scale = 1.0
        self._refresh_icon = None
        self._hover_row = -1
        self._hover_button = ""
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

    def _button_at(self, cell_rect: QRect, pos) -> str:
        refresh_rect, download_rect = self._button_rects(cell_rect)
        if refresh_rect.contains(pos):
            return "refresh"
        if download_rect.contains(pos):
            return "download"
        return ""

    def clear_hover(self, view=None) -> None:
        if self._hover_row < 0 and not self._hover_button:
            return
        row = self._hover_row
        self._hover_row = -1
        self._hover_button = ""
        if view is not None and row >= 0:
            index = view.model().index(row, 3)
            view.viewport().update(view.visualRect(index))

    def paint(self, painter: QPainter, option, index) -> None:
        item_option = QStyleOptionViewItem(option)
        item_option.state &= ~QStyle.State_MouseOver
        super().paint(painter, item_option, index)
        self._draw_cell_background(painter, option, index)
        row_obj: TrackListRow | None = index.data(Qt.UserRole)
        state = getattr(row_obj, "download_state", DownloadState.IDLE) if row_obj else DownloadState.IDLE

        refresh_rect, download_rect = self._button_rects(option.rect)
        hover_refresh = self._hover_row == index.row() and self._hover_button == "refresh"
        hover_download = self._hover_row == index.row() and self._hover_button == "download"
        if hover_refresh:
            self._draw_hover_panel(painter, refresh_rect)
        if hover_download and state != DownloadState.LOADING:
            self._draw_hover_panel(painter, download_rect)

        refresh_opt = QStyleOptionButton()
        refresh_opt.rect = refresh_rect
        refresh_opt.icon = self._refresh_icon
        icon_size = int(round(14 * self._ui_scale))
        refresh_opt.iconSize = QSize(icon_size, icon_size)
        refresh_opt.state = QStyle.State_Enabled | QStyle.State_Raised
        if hover_refresh:
            refresh_opt.state |= QStyle.State_MouseOver

        download_opt = QStyleOptionButton()
        download_opt.rect = download_rect
        download_opt.text = {
            DownloadState.LOADING: "Working...",
            DownloadState.SUCCESS: "Done",
            DownloadState.ERROR: "Retry",
        }.get(state, "Download")
        download_opt.state = QStyle.State_None if state == DownloadState.LOADING else QStyle.State_Enabled | QStyle.State_Raised
        if hover_download and state != DownloadState.LOADING:
            download_opt.state |= QStyle.State_MouseOver
        QApplication.style().drawControl(QStyle.CE_PushButton, refresh_opt, painter)
        QApplication.style().drawControl(QStyle.CE_PushButton, download_opt, painter)

    def _draw_cell_background(self, painter: QPainter, option, index) -> None:
        if option.state & QStyle.State_Selected:
            color = STYLE_TOKENS.get("color-selection-bg", "#0b2942")
        elif index.row() % 2 == 1:
            color = STYLE_TOKENS.get("color-table-alt", "#111827")
        else:
            color = STYLE_TOKENS.get("color-table-bg", "#0f172a")
        painter.fillRect(option.rect, QColor(color))

    def _draw_hover_panel(self, painter: QPainter, rect: QRect) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor(STYLE_TOKENS.get("color-bg-elevated", "#111827")))
        painter.setPen(QPen(QColor(STYLE_TOKENS.get("color-accent", "#38bdf8")), 1))
        painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 6, 6)
        painter.restore()

    def editorEvent(self, event, model, option, index) -> bool:
        if index.column() != 3:
            return False
        if event.type() == QEvent.Type.MouseMove:
            row_obj: TrackListRow | None = index.data(Qt.UserRole)
            is_loading = getattr(row_obj, "download_state", DownloadState.IDLE) == DownloadState.LOADING if row_obj else False
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            button = "" if is_loading else self._button_at(option.rect, pos)
            if self._hover_row != index.row() or self._hover_button != button:
                previous_row = self._hover_row
                self._hover_row = index.row() if button else -1
                self._hover_button = button
                if option.widget is not None:
                    if previous_row >= 0:
                        previous_index = model.index(previous_row, 3)
                        option.widget.viewport().update(option.widget.visualRect(previous_index))
                    option.widget.viewport().update(option.rect)
                    option.widget.viewport().setCursor(
                        QCursor(Qt.CursorShape.PointingHandCursor if button else Qt.CursorShape.ArrowCursor)
                    )
            return bool(button)
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
