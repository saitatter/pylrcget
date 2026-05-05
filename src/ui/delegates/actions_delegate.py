# ui/actions_delegate.py
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QRect, Signal, QSize
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

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
        selected = bool(option.state & QStyle.State_Selected)
        hover_refresh = self._hover_row == index.row() and self._hover_button == "refresh"
        hover_download = self._hover_row == index.row() and self._hover_button == "download"
        icon_size = int(round(14 * self._ui_scale))
        self._draw_action_button(
            painter,
            refresh_rect,
            icon=self._refresh_icon,
            icon_size=QSize(icon_size, icon_size),
            hovered=hover_refresh,
            selected=selected,
        )
        download_text = {
            DownloadState.LOADING: "Working...",
            DownloadState.SUCCESS: "Done",
            DownloadState.ERROR: "Retry",
        }.get(state, "Download")
        self._draw_action_button(
            painter,
            download_rect,
            text=download_text,
            hovered=hover_download and state != DownloadState.LOADING,
            enabled=state != DownloadState.LOADING,
            selected=selected,
        )

    def _draw_cell_background(self, painter: QPainter, option, index) -> None:
        if option.state & QStyle.State_Selected:
            color = STYLE_TOKENS.get("color-selection-bg", "#0b2942")
        elif index.row() % 2 == 1:
            color = STYLE_TOKENS.get("color-table-alt", "#111827")
        else:
            color = STYLE_TOKENS.get("color-table-bg", "#0f172a")
        painter.fillRect(option.rect, QColor(color))

    def _draw_action_button(
        self,
        painter: QPainter,
        rect: QRect,
        *,
        text: str = "",
        icon=None,
        icon_size: QSize | None = None,
        hovered: bool = False,
        enabled: bool = True,
        selected: bool = False,
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        text_key = "color-text" if enabled else "color-disabled-text"
        bg_color = QColor(STYLE_TOKENS.get("color-bg-elevated" if hovered else "color-bg-control", "#172033"))
        border_color = QColor(STYLE_TOKENS.get("color-accent" if hovered else "color-border", "#334155"))
        has_fill = True
        if selected:
            bg_color = QColor(STYLE_TOKENS.get("color-accent", "#38bdf8"))
            bg_color.setAlpha(110 if hovered else 80)
            border_color = QColor(STYLE_TOKENS.get("color-accent", "#38bdf8"))
            border_color.setAlpha(210 if hovered else 130)
            has_fill = hovered
        if not enabled:
            bg_color = QColor(STYLE_TOKENS.get("color-bg-pressed", "#262626"))
            border_color = QColor(STYLE_TOKENS.get("color-disabled-border", "#4b5563"))
            if selected:
                bg_color = QColor(STYLE_TOKENS.get("color-accent", "#38bdf8"))
                bg_color.setAlpha(24)
                border_color.setAlpha(80)
                has_fill = True

        painter.setBrush(bg_color if has_fill else Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(border_color, 1))
        painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 5, 5)

        if icon is not None:
            size = icon_size or QSize(14, 14)
            icon_rect = QRect(0, 0, size.width(), size.height())
            icon_rect.moveCenter(rect.center())
            icon.paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter)
        elif text:
            painter.setPen(QColor(STYLE_TOKENS.get(text_key, "#e5e7eb")))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
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
