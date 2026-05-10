from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, Qt, Signal
from PySide6.QtGui import QCursor, QPainter, QPen
from PySide6.QtWidgets import (
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from db.models import Track
from ui.delegates.actions_delegate import _theme_color


TRACK_ID_ROLE = Qt.ItemDataRole.UserRole
TRACK_ROLE = Qt.ItemDataRole.UserRole + 1
HAS_LYRICS_ROLE = Qt.ItemDataRole.UserRole + 2


class LyricsDiffButtonDelegate(QStyledItemDelegate):
    diffClicked = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._hover_row = -1

    def _button_rect(self, cell_rect: QRect) -> QRect:
        button_w = 54
        button_h = 26
        return QRect(
            cell_rect.center().x() - button_w // 2,
            cell_rect.center().y() - button_h // 2,
            button_w,
            button_h,
        )

    def paint(self, painter: QPainter, option, index) -> None:
        item_option = QStyleOptionViewItem(option)
        item_option.state &= ~QStyle.State_MouseOver
        super().paint(painter, item_option, index)

        track = index.data(TRACK_ROLE)
        enabled = bool(index.data(HAS_LYRICS_ROLE)) and isinstance(track, Track)
        hovered = self._hover_row == index.row()
        selected = bool(option.state & QStyle.State_Selected)
        self._draw_button(
            painter,
            self._button_rect(option.rect),
            hovered=hovered,
            enabled=enabled,
            selected=selected,
        )

    def _draw_button(self, painter: QPainter, rect: QRect, *, hovered: bool, enabled: bool, selected: bool) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        text_key = "color-text" if enabled else "color-disabled-text"
        bg_color = _theme_color("color-bg-elevated" if hovered else "color-bg-control", "#172033")
        border_color = _theme_color("color-accent" if hovered else "color-border", "#334155")
        has_fill = True
        if selected:
            bg_color = _theme_color("color-accent", "#38bdf8")
            bg_color.setAlpha(150 if hovered else 118)
            border_color = _theme_color("color-accent", "#38bdf8")
            border_color.setAlpha(235 if hovered else 205)
            has_fill = True
        if not enabled:
            bg_color = _theme_color("color-bg-pressed", "#262626")
            border_color = _theme_color("color-disabled-border", "#4b5563")
            if selected:
                bg_color = _theme_color("color-accent", "#38bdf8")
                bg_color.setAlpha(24)
                border_color.setAlpha(80)
                has_fill = True

        painter.setBrush(bg_color if has_fill else Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(border_color, 1))
        painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 5, 5)
        painter.setPen(_theme_color(text_key, "#e5e7eb"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Diff")
        painter.restore()

    def editorEvent(self, event, model, option, index) -> bool:
        if index.column() != 6:
            return False
        track = index.data(TRACK_ROLE)
        enabled = bool(index.data(HAS_LYRICS_ROLE)) and isinstance(track, Track)
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        hovered = enabled and self._button_rect(option.rect).contains(pos)

        if event.type() == QEvent.Type.MouseMove:
            previous_row = self._hover_row
            self._hover_row = index.row() if hovered else -1
            if previous_row != self._hover_row and option.widget is not None:
                if previous_row >= 0:
                    option.widget.viewport().update(option.widget.visualRect(model.index(previous_row, 6)))
                option.widget.viewport().update(option.rect)
                option.widget.viewport().setCursor(
                    QCursor(Qt.CursorShape.PointingHandCursor if hovered else Qt.CursorShape.ArrowCursor)
                )
            return hovered

        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            if hovered:
                self.diffClicked.emit(track)
                return True
        return False


class LyricsPropagateDialog(QDialog):
    def __init__(self, matches: list[dict], *, source_lyrics: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sync Lyrics to Similar Tracks")
        self.resize(960, 520)
        self._matches = list(matches)
        self._source_lyrics = (source_lyrics or "").strip()

        layout = QVBoxLayout(self)
        self.summary_label = QLabel(
            f"Review {len(self._matches)} similar track(s). Checked rows will receive the current lyrics."
        )
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Apply", "Track", "Artist", "Album", "Duration", "Match", "Diff"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setMouseTracking(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(6, 74)
        self.diff_delegate = LyricsDiffButtonDelegate(self.table)
        self.diff_delegate.diffClicked.connect(self._show_diff)
        self.table.setItemDelegateForColumn(6, self.diff_delegate)
        layout.addWidget(self.table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Sync Checked")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate()
        if self.table.rowCount():
            self.table.selectRow(0)

    def selected_track_ids(self) -> list[int]:
        selected: list[int] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            track_id = item.data(TRACK_ID_ROLE)
            if track_id is not None:
                selected.append(int(track_id))
        return selected

    def _populate(self) -> None:
        self.table.setRowCount(len(self._matches))
        for row, match in enumerate(self._matches):
            track = match["track"]
            if not isinstance(track, Track):
                continue

            apply_item = QTableWidgetItem("")
            apply_item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            apply_item.setCheckState(Qt.CheckState.Checked if int(match["score"]) >= 85 else Qt.CheckState.Unchecked)
            apply_item.setData(TRACK_ID_ROLE, int(track.id))
            apply_item.setData(TRACK_ROLE, track)
            self.table.setItem(row, 0, apply_item)

            self.table.setItem(row, 1, QTableWidgetItem(_track_label(track)))
            self.table.setItem(row, 2, QTableWidgetItem(track.artist_name or ""))
            self.table.setItem(row, 3, QTableWidgetItem(track.album_name or ""))
            self.table.setItem(row, 4, QTableWidgetItem(_format_duration(track.duration)))
            self.table.setItem(row, 5, QTableWidgetItem(f"{int(match['score'])}%"))
            diff_item = QTableWidgetItem("")
            diff_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            diff_item.setData(TRACK_ROLE, track)
            diff_item.setData(HAS_LYRICS_ROLE, bool(_lyrics_text_for_track(track).strip()))
            diff_item.setToolTip(
                "Compare current lyrics with this track's existing lyrics"
                if diff_item.data(HAS_LYRICS_ROLE)
                else "This track has no existing lyrics to compare"
            )
            self.table.setItem(row, 6, diff_item)

    def _show_diff(self, track: Track) -> None:
        from ui.dialogs.lyrics_diff_dialog import LyricsDiffDialog

        target_lyrics = _lyrics_text_for_track(track)
        dlg = LyricsDiffDialog(
            target_lyrics,
            self._source_lyrics,
            title=f"Lyrics Diff - {track.artist_name} - {track.title}",
            parent=self,
        )
        dlg.exec()


def _track_label(track: Track) -> str:
    number = f"{int(track.track_number):02d}. " if track.track_number is not None else ""
    return f"{number}{track.title or ''}".strip()


def _format_duration(duration: float | int | None) -> str:
    seconds = max(0, int(round(float(duration or 0))))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}:{seconds:02d}"


def _lyrics_text_for_track(track: Track) -> str:
    if track.dirty_lyrics_present:
        dirty_lrc = (track.dirty_lrc_lyrics or "").strip()
        dirty_txt = (track.dirty_txt_lyrics or "").strip()
        if dirty_lrc or dirty_txt:
            return dirty_lrc or dirty_txt
    return (track.lrc_lyrics or "").strip() or (track.txt_lyrics or "").strip()
