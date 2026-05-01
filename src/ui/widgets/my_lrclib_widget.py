from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from db.queries import (
    clear_download_history,
    clear_publish_history,
    get_download_history_rows,
    get_publish_history_rows,
)
from ui.style_loader import load_stylesheet
from ui.theme_tokens import STYLE_TOKENS
from ui.widgets.empty_state_widget import EmptyStateWidget
from ui.widgets.sortable_header_view import SortableHeaderView


TRACK_ID_ROLE = Qt.ItemDataRole.UserRole
TRACK_EXISTS_ROLE = Qt.ItemDataRole.UserRole + 1


class MyLrclibWidget(QWidget):
    playTrack = Signal(int)

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.summary = QFrame()
        self.summary.setObjectName("MyLrclibSummary")
        summary_layout = QGridLayout(self.summary)
        summary_layout.setContentsMargins(12, 12, 12, 12)
        summary_layout.setHorizontalSpacing(10)
        summary_layout.setVerticalSpacing(10)
        self.summary_title = QLabel("My LRCLIB")
        self.summary_title.setObjectName("MyLrclibSummaryTitle")
        self.summary_body = QLabel("Local history for published contributions and lyrics downloads.")
        self.summary_body.setObjectName("MyLrclibSummaryBody")
        self.summary_body.setWordWrap(True)
        summary_layout.addWidget(self.summary_title, 0, 0, 1, 4)
        summary_layout.addWidget(self.summary_body, 1, 0, 1, 4)

        self.card_published = self._build_summary_card("Published")
        self.card_downloads = self._build_summary_card("Downloads")
        self.card_synced = self._build_summary_card("Synced")
        self.card_failures = self._build_summary_card("Needs attention")
        summary_layout.addWidget(self.card_published, 2, 0)
        summary_layout.addWidget(self.card_downloads, 2, 1)
        summary_layout.addWidget(self.card_synced, 2, 2)
        summary_layout.addWidget(self.card_failures, 2, 3)
        root.addWidget(self.summary)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("MyLrclibTabs")
        root.addWidget(self.tabs)

        self.publish_table, self.publish_model, self.publish_empty = self._build_table_page(
            table_name="MyLrclibTable",
            headers=["Status", "Type", "Title", "Artist", "Album", "Published", "LRCLIB"],
            column_widths=[90, 80, 260, 180, 180, 160],
            empty_icon="check.svg",
            empty_title="No published contributions yet",
            empty_body="Publish synced or plain lyrics from the editor and your contribution history will appear here with timestamps and source instance details.",
            default_sort_column=5,
        )
        self.download_table, self.download_model, self.download_empty = self._build_table_page(
            table_name="DownloadHistoryTable",
            headers=["Result", "Mode", "Title", "Artist", "Album", "Downloaded", "Details"],
            column_widths=[90, 120, 260, 180, 180, 160],
            empty_icon="download.svg",
            empty_title="No lyrics downloads yet",
            empty_body="Use Download Missing or download lyrics for a selection, and the results will be kept here as a persistent local history.",
            default_sort_column=5,
        )
        self.clear_published_btn = self._build_clear_button("Clear Published")
        self.clear_downloads_btn = self._build_clear_button("Clear Downloads")
        self.clear_published_btn.clicked.connect(self._clear_published_history)
        self.clear_downloads_btn.clicked.connect(self._clear_download_history)

        self.tabs.addTab(self._wrap_page(self.publish_table, self.publish_empty, self.clear_published_btn), "Published")
        self.tabs.addTab(self._wrap_page(self.download_table, self.download_empty, self.clear_downloads_btn), "Downloads")

        self._apply_styles()
        self.refresh()

    @staticmethod
    def _build_summary_card(label: str) -> QFrame:
        card = QFrame()
        card.setObjectName("MyLrclibMetricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(2)
        title = QLabel(label)
        title.setObjectName("MyLrclibMetricLabel")
        value = QLabel("0")
        value.setObjectName("MyLrclibMetricValue")
        value.setProperty("metricValue", True)
        layout.addWidget(title)
        layout.addWidget(value)
        card._value_label = value  # type: ignore[attr-defined]
        return card

    @staticmethod
    def _set_card_value(card: QFrame, value: int) -> None:
        value_label = getattr(card, "_value_label", None)
        if isinstance(value_label, QLabel):
            value_label.setText(str(int(value)))

    @staticmethod
    def _build_clear_button(text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("MyLrclibClearButton")
        return button

    def _build_table_page(
        self,
        *,
        table_name: str,
        headers: list[str],
        column_widths: list[int],
        empty_icon: str,
        empty_title: str,
        empty_body: str,
        default_sort_column: int,
    ) -> tuple[QTableView, QStandardItemModel, EmptyStateWidget]:
        table = QTableView()
        table.setObjectName(table_name)
        model = QStandardItemModel(0, len(headers), self)
        model.setHorizontalHeaderLabels(headers)
        table.setModel(model)
        header = SortableHeaderView(
            Qt.Orientation.Horizontal,
            table,
            default_sort_column=default_sort_column,
            default_sort_order=Qt.SortOrder.DescendingOrder,
            non_sortable_columns=set(),
        )
        table.setHorizontalHeader(header)
        table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        table.setSortingEnabled(True)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(
            lambda pos, t=table, m=model: self._on_context_menu(t, m, pos)
        )
        table.doubleClicked.connect(lambda index, m=model: self._on_double_click(m, index))
        for idx, width in enumerate(column_widths):
            table.setColumnWidth(idx, width)
        header.setStretchLastSection(True)

        empty_state = EmptyStateWidget()
        empty_state.configure(
            icon_name=empty_icon,
            title=empty_title,
            body=empty_body,
            action_text=None,
        )
        return table, model, empty_state

    @staticmethod
    def _wrap_page(table: QTableView, empty_state: EmptyStateWidget, clear_button: QPushButton) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addStretch(1)
        actions.addWidget(clear_button)
        root.addLayout(actions)
        root.addWidget(table)
        root.addWidget(empty_state)
        return page

    def refresh(self) -> None:
        self.refresh_published()
        self.refresh_downloads()

    def refresh_published(self) -> None:
        self.publish_model.setRowCount(0)
        rows = get_publish_history_rows(self.app_state.db, limit=500)
        for row in rows:
            self.publish_model.appendRow(
                [
                    self._item(
                        str(row["publish_status"] or "Published"),
                        row,
                        color=STYLE_TOKENS.get("color-success-border", "#16a34a"),
                    ),
                    self._item(
                        self._display_kind(row["publish_kind"]),
                        row,
                        color=self._kind_color(row["publish_kind"]),
                    ),
                    self._item(str(row["title"] or ""), row),
                    self._item(str(row["artist_name"] or ""), row),
                    self._item(str(row["album_name"] or ""), row),
                    self._item(str(row["published_at"] or ""), row),
                    self._item(str(row["lrclib_instance"] or ""), row),
                ]
            )
        self._apply_page_visibility(self.publish_table, self.publish_empty, self.publish_model.rowCount() > 0)
        self.clear_published_btn.setEnabled(self.publish_model.rowCount() > 0)

    def refresh_downloads(self) -> None:
        self.download_model.setRowCount(0)
        rows = get_download_history_rows(self.app_state.db, limit=500)
        for row in rows:
            self.download_model.appendRow(
                [
                    self._item(
                        self._display_download_status(row["download_status"]),
                        row,
                        color=self._download_status_color(row["download_status"]),
                    ),
                    self._item(
                        self._display_download_mode(row["download_mode"]),
                        row,
                        color=STYLE_TOKENS.get("color-text-soft", "#94a3b8"),
                    ),
                    self._item(str(row["title"] or ""), row),
                    self._item(str(row["artist_name"] or ""), row),
                    self._item(str(row["album_name"] or ""), row),
                    self._item(str(row["downloaded_at"] or ""), row),
                    self._item(str(row["message"] or ""), row),
                ]
            )
        self._apply_page_visibility(self.download_table, self.download_empty, self.download_model.rowCount() > 0)
        self.clear_downloads_btn.setEnabled(self.download_model.rowCount() > 0)
        self._update_summary(rows)

    @staticmethod
    def _apply_page_visibility(table: QTableView, empty_state: EmptyStateWidget, has_rows: bool) -> None:
        table.setVisible(has_rows)
        empty_state.setVisible(not has_rows)

    def _item(self, text: str, row, *, color: str | None = None) -> QStandardItem:
        item = QStandardItem(text)
        item.setEditable(False)
        item.setData(int(row["track_id"]) if row["track_id"] is not None else None, TRACK_ID_ROLE)
        item.setData(bool(row["track_exists"]), TRACK_EXISTS_ROLE)
        if color:
            item.setForeground(QColor(color))
        return item

    def _update_summary(self, download_rows: list) -> None:
        publish_count = self.publish_model.rowCount()
        download_count = self.download_model.rowCount()
        synced_count = 0
        attention_count = 0

        for row_index in range(self.publish_model.rowCount()):
            kind = (self.publish_model.index(row_index, 1).data() or "").strip().lower()
            if kind == "synced":
                synced_count += 1

        for row in download_rows:
            status = str(row["download_status"] or "").strip().lower()
            if status in {"error", "not_found"}:
                attention_count += 1

        self._set_card_value(self.card_published, publish_count)
        self._set_card_value(self.card_downloads, download_count)
        self._set_card_value(self.card_synced, synced_count)
        self._set_card_value(self.card_failures, attention_count)
        self.tabs.setTabText(0, f"Published ({publish_count})")
        self.tabs.setTabText(1, f"Downloads ({download_count})")

    @staticmethod
    def _row_track_id(model: QStandardItemModel, row_index: int) -> int | None:
        if row_index < 0:
            return None
        index = model.index(row_index, 0)
        track_id = index.data(TRACK_ID_ROLE)
        track_exists = bool(index.data(TRACK_EXISTS_ROLE))
        if track_id is None or not track_exists:
            return None
        return int(track_id)

    def _on_double_click(self, model: QStandardItemModel, index) -> None:
        if not index.isValid():
            return
        track_id = self._row_track_id(model, index.row())
        if track_id is not None:
            self.playTrack.emit(track_id)

    def _on_context_menu(self, table: QTableView, model: QStandardItemModel, pos) -> None:
        idx = table.indexAt(pos)
        if not idx.isValid():
            return
        track_id = self._row_track_id(model, idx.row())
        menu = QMenu(self)
        info = menu.addAction(model.index(idx.row(), 2).data() or "Lyrics history")
        info.setEnabled(False)
        menu.addSeparator()
        act_play = menu.addAction("Play track")
        act_play.setEnabled(track_id is not None)
        chosen = menu.exec(table.viewport().mapToGlobal(pos))
        if chosen == act_play and track_id is not None:
            self.playTrack.emit(track_id)

    def _confirm_clear(self, title: str, text: str) -> bool:
        return QMessageBox.question(
            self,
            title,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes

    def _clear_published_history(self) -> None:
        if self.publish_model.rowCount() <= 0:
            return
        if not self._confirm_clear(
            "Clear Published History",
            "Clear all local published contribution history?",
        ):
            return
        clear_publish_history(self.app_state.db)
        self.refresh()

    def _clear_download_history(self) -> None:
        if self.download_model.rowCount() <= 0:
            return
        if not self._confirm_clear(
            "Clear Download History",
            "Clear all local lyrics download history?",
        ):
            return
        clear_download_history(self.app_state.db)
        self.refresh()

    @staticmethod
    def _display_kind(value: str | None) -> str:
        text = (value or "").strip().lower()
        if text == "synced":
            return "Synced"
        if text == "plain":
            return "Plain"
        return text.title() if text else "Unknown"

    @staticmethod
    def _kind_color(value: str | None) -> str:
        text = (value or "").strip().lower()
        if text == "synced":
            return STYLE_TOKENS.get("color-success-border", "#16a34a")
        if text == "plain":
            return STYLE_TOKENS.get("color-warning-border", "#f59e0b")
        return STYLE_TOKENS.get("color-text-soft", "#94a3b8")

    @staticmethod
    def _display_download_mode(value: str | None) -> str:
        mapping = {
            "prefer_synced": "Prefer synced",
            "synced_only": "Synced only",
            "plain_only": "Plain only",
        }
        return mapping.get((value or "").strip(), (value or "").strip().title() or "Unknown")

    @staticmethod
    def _display_download_status(value: str | None) -> str:
        mapping = {
            "synced": "Synced",
            "plain": "Plain",
            "not_found": "Not Found",
            "instrumental": "Instrumental",
            "error": "Error",
        }
        return mapping.get((value or "").strip(), (value or "").strip().title() or "Unknown")

    @staticmethod
    def _download_status_color(value: str | None) -> str:
        text = (value or "").strip().lower()
        if text == "synced":
            return STYLE_TOKENS.get("color-success-border", "#16a34a")
        if text == "plain":
            return STYLE_TOKENS.get("color-warning-border", "#f59e0b")
        if text == "instrumental":
            return STYLE_TOKENS.get("color-accent-alt", "#60a5fa")
        return STYLE_TOKENS.get("color-error-border", "#ef4444")

    def _apply_styles(self) -> None:
        qss = load_stylesheet("data_table.qss", table_name="MyLrclibTable")
        qss += "\n" + load_stylesheet("data_table.qss", table_name="DownloadHistoryTable")
        qss += """
QFrame#MyLrclibSummary {
    background: %(panel)s;
    border: 1px solid %(border)s;
    border-radius: %(radius)s;
}
QLabel#MyLrclibSummaryTitle {
    color: %(text_strong)s;
    font-size: 16px;
    font-weight: 700;
}
QLabel#MyLrclibSummaryBody {
    color: %(text_soft)s;
    font-size: 12px;
}
QFrame#MyLrclibMetricCard {
    background: %(app)s;
    border: 1px solid %(border)s;
    border-radius: %(radius_sm)s;
}
QLabel#MyLrclibMetricLabel {
    color: %(text_muted)s;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 600;
}
QLabel#MyLrclibMetricValue {
    color: %(text_strong)s;
    font-size: 24px;
    font-weight: 700;
}
QPushButton#MyLrclibClearButton {
    padding: 5px 12px;
}
        """ % {
            "panel": STYLE_TOKENS.get("color-bg-panel", "#111827"),
            "app": STYLE_TOKENS.get("color-bg-app", "#0f172a"),
            "border": STYLE_TOKENS.get("color-border-strong", "#334155"),
            "radius": STYLE_TOKENS.get("radius-lg", "14px"),
            "radius_sm": STYLE_TOKENS.get("radius-md", "10px"),
            "text_strong": STYLE_TOKENS.get("color-text-strong", "#f8fafc"),
            "text_soft": STYLE_TOKENS.get("color-text-soft", "#94a3b8"),
            "text_muted": STYLE_TOKENS.get("color-text-muted", "#64748b"),
        }
        self.setStyleSheet(qss)
