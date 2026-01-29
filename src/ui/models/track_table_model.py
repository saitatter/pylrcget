# ui/track_table_model.py
from __future__ import annotations
from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex
from core.tracklist_models import TrackListRow

def fmt_duration(seconds: int | None) -> str:
    if seconds is None:
        return ""
    m = seconds // 60
    s = seconds % 60
    return f"{m}:{s:02d}"

class TrackTableModel(QAbstractTableModel):
    def __init__(self, rows):
        super().__init__()
        self._rows = list(rows)

    def set_rows(self, rows):
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 4

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return ["Track", "Duration", "Lyrics", ""][section]

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return f"{row.artist} — {row.title}" if row.artist else row.title
            if col == 1:
                return fmt_duration(row.duration_s)
            if col == 2:
                return row.lyrics_state
            if col == 3:
                return ""
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