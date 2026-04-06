from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate


class TrackInfoDelegate(QStyledItemDelegate):
    artistClicked = Signal(int)
    albumClicked = Signal(int)

    @staticmethod
    def _clean_metadata(value: str | None, *, kind: str) -> str:
        text = (value or "").strip()
        placeholders = {
            "album": {"unknown album", "album"},
            "artist": {"unknown artist", "artist"},
        }
        if text.casefold() in placeholders.get(kind, set()):
            return ""
        return text

    def paint(self, painter: QPainter, option, index) -> None:
        row = index.data(Qt.UserRole)
        if not row:
            super().paint(painter, option, index)
            return

        style = option.widget.style() if option.widget else QApplication.style()
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget)

        rect = option.rect.adjusted(10, 6, -10, -6)
        title_font = QFont(option.font)
        title_font.setPointSize(max(title_font.pointSize(), 10))
        title_font.setWeight(QFont.Weight.DemiBold)

        meta_font = QFont(option.font)
        meta_font.setPointSize(max(meta_font.pointSize() - 1, 9))

        is_selected = bool(option.state & option.state.State_Selected)
        title_color = option.palette.highlightedText().color() if is_selected else option.palette.text().color()
        meta_color = option.palette.highlightedText().color() if is_selected else QColor("#94a3b8")
        link_color = option.palette.highlightedText().color() if is_selected else QColor("#60a5fa")

        title_metrics = QFontMetrics(title_font)
        meta_metrics = QFontMetrics(meta_font)

        title_rect = QRect(rect.left(), rect.top(), rect.width(), title_metrics.height())
        meta_rect = QRect(rect.left(), rect.bottom() - meta_metrics.height(), rect.width(), meta_metrics.height())

        painter.save()
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        painter.setFont(title_font)
        painter.setPen(title_color)
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, title_metrics.elidedText(row.title or "", Qt.ElideRight, title_rect.width()))

        painter.setFont(meta_font)
        album_text = self._clean_metadata(row.album, kind="album")
        artist_text = self._clean_metadata(row.artist, kind="artist")
        album_clickable = bool(album_text and row.album_id is not None)
        artist_clickable = bool(artist_text and row.artist_id is not None)
        album_display = album_text or "N/A"
        artist_display = artist_text or "N/A"
        separator = " | "

        x = meta_rect.left()
        if album_display:
            album_width = meta_metrics.horizontalAdvance(album_display)
            painter.setPen(link_color if album_clickable else meta_color)
            painter.drawText(
                QRect(x, meta_rect.top(), max(0, meta_rect.width() - (x - meta_rect.left())), meta_rect.height()),
                Qt.AlignLeft | Qt.AlignVCenter,
                meta_metrics.elidedText(album_display, Qt.ElideRight, meta_rect.width()),
            )
            x += min(album_width, meta_rect.width())

        if x < meta_rect.right():
            painter.setPen(meta_color)
            sep_width = meta_metrics.horizontalAdvance(separator)
            painter.drawText(QRect(x, meta_rect.top(), sep_width, meta_rect.height()), Qt.AlignLeft | Qt.AlignVCenter, separator)
            x += sep_width

        if artist_display and x < meta_rect.right():
            painter.setPen(link_color if artist_clickable else meta_color)
            remaining = max(0, meta_rect.right() - x)
            painter.drawText(
                QRect(x, meta_rect.top(), remaining, meta_rect.height()),
                Qt.AlignLeft | Qt.AlignVCenter,
                meta_metrics.elidedText(artist_display, Qt.ElideRight, remaining),
            )

        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height(), 44))

    def editorEvent(self, event, model, option, index):
        if index.column() != 0:
            return False
        row = index.data(Qt.UserRole)
        if not row:
            return False

        if event.type() == QEvent.Type.MouseMove:
            target = self._hit_target(option.rect, option.font, row, event.pos())
            if option.widget:
                option.widget.viewport().setCursor(QCursor(Qt.CursorShape.PointingHandCursor if target else Qt.CursorShape.ArrowCursor))
            return False

        if event.type() == QEvent.Type.Leave and option.widget:
            option.widget.viewport().unsetCursor()
            return False

        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            target = self._hit_target(option.rect, option.font, row, event.pos())
            if target == "album" and row.album_id is not None and (row.album or "").strip():
                self.albumClicked.emit(int(row.album_id))
                return True
            if target == "artist" and row.artist_id is not None and (row.artist or "").strip():
                self.artistClicked.emit(int(row.artist_id))
                return True
        return False

    def _hit_target(self, rect: QRect, base_font: QFont, row, pos) -> str | None:
        content = rect.adjusted(10, 6, -10, -6)
        meta_font = QFont(base_font)
        meta_font.setPointSize(max(meta_font.pointSize() - 1, 9))
        metrics = QFontMetrics(meta_font)
        meta_rect = QRect(content.left(), content.bottom() - metrics.height(), content.width(), metrics.height())
        if not meta_rect.contains(pos):
            return None

        album_text = self._clean_metadata(row.album, kind="album")
        artist_text = self._clean_metadata(row.artist, kind="artist")
        separator = " | "
        x = meta_rect.left()

        if album_text:
            album_width = metrics.horizontalAdvance(album_text)
            if QRect(x, meta_rect.top(), album_width, meta_rect.height()).contains(pos):
                return "album"
            x += album_width

        x += metrics.horizontalAdvance(separator)

        if artist_text:
            artist_width = metrics.horizontalAdvance(artist_text)
            if QRect(x, meta_rect.top(), artist_width, meta_rect.height()).contains(pos):
                return "artist"

        return None
