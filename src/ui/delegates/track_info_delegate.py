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
        album_visible, artist_visible, separator_visible, album_rect, artist_rect = self._metadata_layout(
            meta_rect, meta_metrics, row
        )

        if album_visible:
            painter.setPen(link_color if album_clickable else meta_color)
            painter.drawText(album_rect, Qt.AlignLeft | Qt.AlignVCenter, album_visible)

        if separator_visible:
            painter.setPen(meta_color)
            sep_x = album_rect.right()
            sep_width = meta_metrics.horizontalAdvance(separator_visible)
            painter.drawText(QRect(sep_x, meta_rect.top(), sep_width, meta_rect.height()), Qt.AlignLeft | Qt.AlignVCenter, separator_visible)

        if artist_visible:
            painter.setPen(link_color if artist_clickable else meta_color)
            painter.drawText(artist_rect, Qt.AlignLeft | Qt.AlignVCenter, artist_visible)

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
        _, _, _, album_rect, artist_rect = self._metadata_layout(meta_rect, metrics, row)

        if album_text and row.album_id is not None and album_rect.isValid() and album_rect.contains(pos):
            return "album"
        if artist_text and row.artist_id is not None and artist_rect.isValid() and artist_rect.contains(pos):
            return "artist"

        return None

    def _metadata_layout(self, meta_rect: QRect, metrics: QFontMetrics, row) -> tuple[str, str, str, QRect, QRect]:
        album_display = self._clean_metadata(row.album, kind="album") or "N/A"
        artist_display = self._clean_metadata(row.artist, kind="artist") or "N/A"
        separator = " | "

        album_visible = metrics.elidedText(album_display, Qt.ElideRight, meta_rect.width())
        album_width = min(metrics.horizontalAdvance(album_visible), meta_rect.width())
        album_rect = QRect(meta_rect.left(), meta_rect.top(), max(0, album_width), meta_rect.height())

        remaining_after_album = max(0, meta_rect.width() - album_width)
        sep_width = metrics.horizontalAdvance(separator) if remaining_after_album > 0 else 0
        separator_visible = separator if sep_width > 0 and remaining_after_album >= sep_width else ""

        artist_x = meta_rect.left() + album_width + sep_width
        artist_width_available = max(0, meta_rect.right() - artist_x)
        artist_visible = metrics.elidedText(artist_display, Qt.ElideRight, artist_width_available) if artist_width_available > 0 else ""
        artist_width = metrics.horizontalAdvance(artist_visible) if artist_visible else 0
        artist_rect = QRect(artist_x, meta_rect.top(), max(0, artist_width), meta_rect.height())

        return album_visible, artist_visible, separator_visible, album_rect, artist_rect
