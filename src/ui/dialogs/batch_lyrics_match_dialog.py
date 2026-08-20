from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ui.services.lyrics_match_retry import LyricsMatchCandidate

CANDIDATE_ROLE = Qt.ItemDataRole.UserRole


class BatchLyricsMatchDialog(QDialog):
    def __init__(self, candidates: list[LyricsMatchCandidate], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review LRCLIB Matches")
        self.resize(980, 520)
        self._candidates = list(candidates)

        layout = QVBoxLayout(self)
        self.summary_label = QLabel(
            f"Review {len(self._candidates)} LRCLIB match candidate(s). Checked rows will be written to your library."
        )
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Apply", "Track", "Best match", "Album", "Score", "Type", "Found by"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Commit Checked")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate()

    def selected_candidates(self) -> list[LyricsMatchCandidate]:
        selected: list[LyricsMatchCandidate] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            candidate = item.data(CANDIDATE_ROLE)
            if isinstance(candidate, LyricsMatchCandidate):
                selected.append(candidate)
        return selected

    def _populate(self) -> None:
        self.table.setRowCount(len(self._candidates))
        for row, candidate in enumerate(self._candidates):
            apply_item = QTableWidgetItem("")
            apply_item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            apply_item.setCheckState(Qt.CheckState.Checked if candidate.score >= 72 else Qt.CheckState.Unchecked)
            apply_item.setData(CANDIDATE_ROLE, candidate)
            self.table.setItem(row, 0, apply_item)

            self.table.setItem(row, 1, QTableWidgetItem(candidate.track_label))
            self.table.setItem(row, 2, QTableWidgetItem(f"{candidate.artist_name} - {candidate.track_name}".strip(" -")))
            self.table.setItem(row, 3, QTableWidgetItem(candidate.album_name))
            self.table.setItem(row, 4, QTableWidgetItem(f"{candidate.score}%"))
            self.table.setItem(row, 5, QTableWidgetItem(candidate.kind))
            self.table.setItem(row, 6, QTableWidgetItem(candidate.query_label))
