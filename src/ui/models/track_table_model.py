# ui/track_table_model.py
from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont

from core.tracklist_models import LyricsState, TrackListRow
from ui.theme_tokens import STYLE_TOKENS


def fmt_duration(seconds: int | None) -> str:
    if seconds is None:
        return ""
    m = seconds // 60
    s = seconds % 60
    return f"{m}:{s:02d}"


class TrackTableModel(QAbstractTableModel):
    def __init__(self, rows: Sequence[TrackListRow]) -> None:
        super().__init__()
        self._rows: list[TrackListRow] = list(rows)

    def set_rows(self, rows: Sequence[TrackListRow]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def append_rows(self, rows: Sequence[TrackListRow]) -> None:
        new_rows = list(rows)
        if not new_rows:
            return
        start = len(self._rows)
        end = start + len(new_rows) - 1
        self.beginInsertRows(QModelIndex(), start, end)
        self._rows.extend(new_rows)
        self.endInsertRows()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        del parent
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        del parent
        return 5

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> str | None:
        if orientation != Qt.Horizontal:
            return None
        if role == Qt.DisplayRole:
            return ["#", "Track", "Duration", "Lyrics", ""][section]
        if role == Qt.ToolTipRole:
            return [
                "Track number",
                "Artist — Title",
                "Track duration",
                "Lyrics status: None / Plain / Synced / Instrumental",
                "Actions",
            ][section]
        if role == Qt.TextAlignmentRole and section in {0, 2, 3, 4}:
            return int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        return None

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> object:
        if not index.isValid():
            return None
        row: TrackListRow = self._rows[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return str(row.track_number) if row.track_number is not None else ""
            if col == 1:
                text = f"{row.artist} — {row.title}" if row.artist else row.title
                return f"⊜ {text}" if row.is_duplicate else text
            if col == 2:
                return fmt_duration(row.duration_s)
            if col == 3:
                label = {
                    LyricsState.NONE: "No lyrics",
                    LyricsState.PLAIN: "Plain",
                    LyricsState.SYNCED: "Synced",
                    LyricsState.INSTRUMENTAL: "Instrumental",
                }.get(row.lyrics_state, row.lyrics_state)
                return f"{label} *" if row.has_dirty_lyrics else label
            if col == 4:
                return ""
        if role == Qt.ForegroundRole and col == 3:
            if row.has_dirty_lyrics:
                return QColor(STYLE_TOKENS.get("color-warning-border", "#f59e0b"))
            color_map = {
                LyricsState.NONE: QColor(STYLE_TOKENS.get("color-error-border", "#ef4444")),
                LyricsState.PLAIN: QColor(STYLE_TOKENS.get("color-warning-border", "#f59e0b")),
                LyricsState.SYNCED: QColor(STYLE_TOKENS.get("color-success-border", "#22c55e")),
                LyricsState.INSTRUMENTAL: QColor(STYLE_TOKENS.get("color-accent-alt", "#60a5fa")),
            }
            return color_map.get(row.lyrics_state, QColor(STYLE_TOKENS.get("color-text-muted", "#94a3b8")))
        if role == Qt.FontRole and col == 3:
            font = QFont()
            font.setWeight(QFont.Weight.Bold if row.has_dirty_lyrics else QFont.Weight.DemiBold)
            font.setItalic(bool(row.has_dirty_lyrics))
            return font
        if role == Qt.TextAlignmentRole and col in {0, 2, 3, 4}:
            return int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ToolTipRole and col == 1 and row.is_duplicate:
            return "Possible duplicate: another track shares the same title, artist, and duration."
        if role == Qt.UserRole:
            return row
        return None
    
    def track_id_at(self, row: int) -> int | None:
        if row < 0 or row >= len(self._rows):
            return None
        r: TrackListRow = self._rows[row]
        return int(r.track_id)

    def row_for_track_id(self, track_id: int) -> int:
        for i, r in enumerate(self._rows):
            if int(r.track_id) == int(track_id):
                return i
        return -1
    
    def all_track_ids(self) -> list[int]:
        return [int(r.track_id) for r in self._rows]
