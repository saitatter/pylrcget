from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from db.models import Track


TRACK_ID_ROLE = Qt.ItemDataRole.UserRole


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
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Sync Checked")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate()

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
            self.table.setItem(row, 0, apply_item)

            self.table.setItem(row, 1, QTableWidgetItem(_track_label(track)))
            self.table.setItem(row, 2, QTableWidgetItem(track.artist_name or ""))
            self.table.setItem(row, 3, QTableWidgetItem(track.album_name or ""))
            self.table.setItem(row, 4, QTableWidgetItem(_format_duration(track.duration)))
            self.table.setItem(row, 5, QTableWidgetItem(f"{int(match['score'])}%"))
            self.table.setCellWidget(row, 6, self._make_diff_button(track))

    def _make_diff_button(self, track: Track) -> QPushButton:
        button = QPushButton("Diff")
        target_lyrics = _lyrics_text_for_track(track)
        button.setEnabled(bool(target_lyrics.strip()))
        button.setToolTip(
            "Compare current lyrics with this track's existing lyrics"
            if target_lyrics.strip()
            else "This track has no existing lyrics to compare"
        )
        button.clicked.connect(lambda _checked=False, t=track: self._show_diff(t))
        return button

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
