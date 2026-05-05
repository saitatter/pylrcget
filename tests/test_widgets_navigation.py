from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPointF, QRect
from PySide6.QtGui import QMouseEvent, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QHeaderView, QPushButton, QStyleOptionViewItem, QTableView, QWidget

from core.tracklist_models import DownloadState, LyricsState, TrackListRow
from ui.delegates.actions_delegate import ActionsDelegate
from ui.library_routes import albums_detail, artists_detail, tracks_album, tracks_artist
from ui.controllers.top_bar_controller import TopBarController
from ui.widgets.hotkey_hints import HotkeyHintManager
from ui.widgets.lrclib_browser_widget import _BrowserPublishDialog
from ui.widgets.lyrics_editor_widget import LyricsEditorWidget, TIMESTAMP_MS_ROLE
from ui.main_window import MainWindow
from tests.test_support import (
    HAS_QT,
    AlbumListWidget,
    ArtistListWidget,
    TrackListWidget,
    Qt,
    qt_app,
    simple_app_state,
)


@unittest.skipUnless(HAS_QT, "PySide6 is required for widget tests")
class NavigationBucketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_app()

    def test_album_widget_merges_unknown_album_bucket(self):
        app_state = simple_app_state()
        widget = AlbumListWidget(app_state)
        try:
            rows = [
                {"album_id": 1, "album_name": "Unknown Album", "artist_name": "Artist A", "track_count": 2},
                {"album_id": 2, "album_name": "Album", "artist_name": "Artist B", "track_count": 3},
                {"album_id": 3, "album_name": "Real Album", "artist_name": "Artist C", "track_count": 1},
            ]
            with patch("ui.widgets.album_list_widget.get_directories", return_value=["C:/Music"]), patch(
                "db.database.get_album_rows", return_value=rows
            ):
                widget.refresh()

            self.assertEqual(widget.model.rowCount(), 2)
            names = [widget.model.index(row, 0).data() for row in range(widget.model.rowCount())]
            self.assertIn("N/A", names)

            na_row = names.index("N/A")
            bucket_ids = widget.model.index(na_row, 0).data(role=Qt.ItemDataRole.UserRole)
            self.assertEqual(bucket_ids, (1, 2))
            self.assertEqual(widget.model.index(na_row, 2).data(), "5")
        finally:
            widget.deleteLater()
            app_state.db.close()

    def test_artist_widget_merges_unknown_artist_bucket(self):
        app_state = simple_app_state()
        widget = ArtistListWidget(app_state)
        try:
            rows = [
                {"artist_id": 1, "artist_name": "Unknown Artist", "album_count": 2, "track_count": 4},
                {"artist_id": 2, "artist_name": "Artist", "album_count": 1, "track_count": 3},
                {"artist_id": 3, "artist_name": "Real Artist", "album_count": 1, "track_count": 2},
            ]
            with patch("ui.widgets.artist_list_widget.get_directories", return_value=["C:/Music"]), patch(
                "db.database.get_artist_rows", return_value=rows
            ):
                widget.refresh()

            self.assertEqual(widget.model.rowCount(), 2)
            names = [widget.model.index(row, 0).data() for row in range(widget.model.rowCount())]
            self.assertIn("N/A", names)

            na_row = names.index("N/A")
            bucket_ids = widget.model.index(na_row, 0).data(role=Qt.ItemDataRole.UserRole)
            self.assertEqual(bucket_ids, (1, 2))
            self.assertEqual(widget.model.index(na_row, 2).data(), "7")
        finally:
            widget.deleteLater()
            app_state.db.close()


@unittest.skipUnless(HAS_QT, "PySide6 is required for widget tests")
class PaginationWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_app()

    def test_album_widget_uses_processed_db_row_count_for_offset(self):
        app_state = simple_app_state()
        widget = AlbumListWidget(app_state)
        widget._page_size = 2
        calls: list[int] = []

        def fake_get_album_rows(**kwargs):
            calls.append(int(kwargs["offset"]))
            if kwargs["offset"] == 0:
                return [
                    {"album_id": 1, "album_name": "Unknown Album", "artist_name": "Artist A", "track_count": 1},
                    {"album_id": 2, "album_name": "Album", "artist_name": "Artist B", "track_count": 1},
                    {"album_id": 3, "album_name": "Real Album", "artist_name": "Artist C", "track_count": 1},
                ]
            return []

        try:
            with patch("ui.widgets.album_list_widget.get_directories", return_value=["C:/Music"]), patch(
                "db.database.get_album_rows", side_effect=fake_get_album_rows
            ):
                widget.refresh()
                widget._load_rows(reset=False)

            self.assertEqual(calls, [0, 2])
            self.assertEqual(widget._loaded_db_rows, 2)
        finally:
            widget.deleteLater()
            app_state.db.close()

    def test_artist_widget_uses_processed_db_row_count_for_offset(self):
        app_state = simple_app_state()
        widget = ArtistListWidget(app_state)
        widget._page_size = 2
        calls: list[int] = []

        def fake_get_artist_rows(db, search_query, **kwargs):
            calls.append(int(kwargs["offset"]))
            if kwargs["offset"] == 0:
                return [
                    {"artist_id": 1, "artist_name": "Unknown Artist", "album_count": 1, "track_count": 1},
                    {"artist_id": 2, "artist_name": "Artist", "album_count": 1, "track_count": 1},
                    {"artist_id": 3, "artist_name": "Real Artist", "album_count": 1, "track_count": 1},
                ]
            return []

        try:
            with patch("ui.widgets.artist_list_widget.get_directories", return_value=["C:/Music"]), patch(
                "db.database.get_artist_rows", side_effect=fake_get_artist_rows
            ):
                widget.refresh()
                widget._load_rows(reset=False)

            self.assertEqual(calls, [0, 2])
            self.assertEqual(widget._loaded_db_rows, 2)
        finally:
            widget.deleteLater()
            app_state.db.close()


@unittest.skipUnless(HAS_QT, "PySide6 is required for widget tests")
class TrackListWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_app()

    def test_apply_route_artist_refreshes_once_and_sets_scope(self):
        app_state = simple_app_state()
        widget = TrackListWidget(app_state)
        try:
            with patch.object(widget, "refresh") as refresh:
                widget.apply_route(tracks_artist((7,), label="Radiohead"))
            refresh.assert_called_once()
            self.assertEqual(widget._artist_id, 7)
            self.assertIsNone(widget._album_id)
            self.assertEqual(widget._scope_label, "Artist: Radiohead")
        finally:
            widget.deleteLater()
            app_state.db.close()

    def test_apply_route_album_refreshes_once_and_sets_scope(self):
        app_state = simple_app_state()
        widget = TrackListWidget(app_state)
        try:
            with patch.object(widget, "refresh") as refresh:
                widget.apply_route(tracks_album((11,), label="Kid A"))
            refresh.assert_called_once()
            self.assertEqual(widget._album_id, 11)
            self.assertIsNone(widget._artist_id)
            self.assertEqual(widget._scope_label, "Album: Kid A")
        finally:
            widget.deleteLater()
            app_state.db.close()

    def test_metadata_link_navigation_targets_album_and_artist_tabs(self):
        app_state = simple_app_state()
        widget = TrackListWidget(app_state)
        routes = []
        try:
            widget.navigateRequested.connect(routes.append)

            widget._emit_artist_navigation(7)
            widget._emit_album_navigation(11)

            self.assertEqual(routes[0], artists_detail((7,)))
            self.assertEqual(routes[1], albums_detail((11,)))
        finally:
            widget.deleteLater()
            app_state.db.close()


@unittest.skipUnless(HAS_QT, "PySide6 is required for widget tests")
class LyricsPasteBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_app()

    def test_plain_lyrics_editor_rejects_rich_text_paste(self):
        widget = LyricsEditorWidget()
        try:
            self.assertFalse(widget.plain.acceptRichText())
        finally:
            widget.deleteLater()

    def test_switch_to_synced_parses_pasted_lrc(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_plain("[ar: Artist]\n[ti: Song]\n[00:01.20] First line\n[00:03.00] Second line")
            widget._toggle_editor_mode()

            self.assertEqual(widget.table.rowCount(), 2)
            self.assertEqual(widget.table.item(0, 1).text(), "First line")
            self.assertEqual(widget.table.item(1, 1).text(), "Second line")
            self.assertEqual(widget.table.item(0, 0).text(), "00:01.20")
            self.assertEqual(widget.table.item(1, 0).text(), "00:03.00")
        finally:
            widget.deleteLater()

    def test_lyrics_quick_actions_have_shortcuts(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_synced([(1200, "First line"), (3000, "Second line")])
            widget.table.selectRow(0)

            self.assertIn("(Left)", widget.btn_shift_minus.toolTip())
            self.assertIn("(Right)", widget.btn_shift_plus.toolTip())
            self.assertEqual(widget._shortcut_shift_minus.key().toString(), "Left")
            self.assertEqual(widget._shortcut_shift_plus.key().toString(), "Right")
            self.assertEqual(widget._shortcut_snap.key().toString(), "Ctrl+Return")
            self.assertEqual(widget._shortcut_add_line.key().toString(), "Ins")
            self.assertEqual(widget._shortcut_delete_line.key().toString(), "Del")
            self.assertIs(widget._shortcut_shift_plus.parent(), widget.table)

            widget._shortcut_shift_plus.activated.emit()
            self.assertEqual(widget.table.item(0, 0).text(), "00:01.30")
            self.assertEqual(widget.table.item(0, 0).data(TIMESTAMP_MS_ROLE), 1300)
        finally:
            widget.deleteLater()

    def test_lyrics_validator_blocks_save_until_autofix(self):
        widget = LyricsEditorWidget()
        emitted: list[tuple[str, str]] = []
        widget.saveRequested.connect(lambda lrc, plain: emitted.append((lrc, plain)))
        try:
            widget._set_synced([(1200, "First line."), (3000, "Second line")])

            self.assertFalse(widget.btn_save.isEnabled())
            self.assertFalse(widget.btn_autofix.isHidden())
            self.assertIn("mark the end", widget.validation_hint.text())

            widget._emit_save()
            self.assertEqual(emitted, [])

            widget._autofix_validation_problems()
            self.assertTrue(widget.btn_save.isEnabled())
            self.assertTrue(widget.btn_autofix.isHidden())

            widget._emit_save()
            self.assertEqual(len(emitted), 1)
            self.assertIn("[00:08.00]", emitted[0][0])
            self.assertNotIn("First line.", emitted[0][0])
        finally:
            widget.deleteLater()

    def test_plain_lyrics_validator_blocks_save(self):
        widget = LyricsEditorWidget()
        emitted: list[tuple[str, str]] = []
        widget.saveRequested.connect(lambda lrc, plain: emitted.append((lrc, plain)))
        try:
            widget._set_plain("[00:01.00] Not plain")

            self.assertFalse(widget.btn_save.isEnabled())
            self.assertFalse(widget.btn_autofix.isEnabled())
            widget._emit_save()
            self.assertEqual(emitted, [])
        finally:
            widget.deleteLater()

    def test_browser_publish_lyrics_fields_reject_rich_text_paste(self):
        dialog = _BrowserPublishDialog("https://lrclib.net")
        try:
            self.assertFalse(dialog._pub_synced.acceptRichText())
            self.assertFalse(dialog._pub_plain.acceptRichText())
        finally:
            dialog.deleteLater()

    def test_track_table_keeps_lyrics_status_column_visible(self):
        app_state = simple_app_state()
        widget = TrackListWidget(app_state)
        try:
            self.assertEqual(widget.model.columnCount(), 4)
            self.assertEqual(widget.model.headerData(2, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole), "Lyrics")
            self.assertEqual(
                widget.model.headerData(2, Qt.Orientation.Horizontal, Qt.ItemDataRole.TextAlignmentRole),
                int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter),
            )
            self.assertFalse(widget.table.isColumnHidden(2))
            self.assertGreaterEqual(widget.table.columnWidth(1), 90)
            self.assertEqual(widget.header.sectionResizeMode(2), QHeaderView.ResizeMode.Fixed)
            self.assertGreaterEqual(widget.table.columnWidth(2), 100)
        finally:
            widget.deleteLater()
            app_state.db.close()

    def test_download_missing_tooltip_does_not_populate_status_bar(self):
        noop = lambda *args, **kwargs: None
        widget = TopBarController(
            on_refresh=noop,
            on_download_missing=noop,
            on_open_settings=noop,
            on_open_about=noop,
            on_toggle_logs=noop,
            on_toggle_hotkey_hints=noop,
            on_schedule_search=noop,
            on_filter_changed=noop,
        )
        try:
            widget.set_download_missing_mode("prefer_synced")
            self.assertIn("Download missing lyrics", widget.btn_download_missing.toolTip())
            self.assertEqual(widget.btn_download_missing.statusTip(), "")
        finally:
            widget.deleteLater()

    def test_player_hotkey_badges_use_shared_badge_style(self):
        stylesheet = Path("src/ui/qss/player_bar.qss").read_text(encoding="utf-8")
        self.assertIn("QLabel#HotkeyHintBadge", stylesheet)
        self.assertIn("background: {{color-accent}};", stylesheet)
        self.assertIn("border-radius: {{radius-pill}};", stylesheet)
        self.assertIn("border-radius: 22px;", stylesheet)
        self.assertIn("border-radius: 14px;", stylesheet)
        self.assertIn("QToolButton#BtnPrev:hover", stylesheet)
        self.assertIn("QToolButton#BtnNext:hover", stylesheet)

    def test_hotkey_badge_uses_window_parent_for_small_buttons(self):
        parent = QWidget()
        button = QPushButton(parent)
        button.setGeometry(10, 10, 28, 28)
        manager = HotkeyHintManager(parent)
        try:
            parent.resize(120, 80)
            parent.show()
            self.app.processEvents()
            manager.register(button, "Ctrl+Left")
            manager.set_visible(True)

            badge = manager._hints[0].badge
            self.assertIs(badge.parentWidget(), parent)
            self.assertEqual(badge.text(), "C<")
            self.assertLessEqual(badge.width(), button.width())
            self.assertGreaterEqual(badge.x(), button.x())
            self.assertLessEqual(badge.x() + badge.width(), button.x() + button.width())
            self.assertTrue(badge.isVisible())
        finally:
            parent.deleteLater()

    def test_track_action_buttons_track_individual_hover(self):
        table = QTableView()
        model = QStandardItemModel(1, 4)
        item = QStandardItem("")
        item.setData(
            TrackListRow(
                track_id=1,
                title="Song",
                artist="Artist",
                artist_id=None,
                album="Album",
                album_id=None,
                duration_s=120,
                lyrics_state=LyricsState.NONE,
                download_state=DownloadState.IDLE,
            ),
            Qt.ItemDataRole.UserRole,
        )
        model.setItem(0, 3, item)
        table.setModel(model)
        delegate = ActionsDelegate(table)
        option = QStyleOptionViewItem()
        option.widget = table
        option.rect = QRect(0, 0, 150, 44)
        refresh_rect, download_rect = delegate._button_rects(option.rect)
        index = model.index(0, 3)
        try:
            refresh_event = QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(refresh_rect.center()),
                QPointF(refresh_rect.center()),
                QPointF(refresh_rect.center()),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
            self.assertTrue(delegate.editorEvent(refresh_event, model, option, index))
            self.assertEqual(delegate._hover_button, "refresh")

            download_event = QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(download_rect.center()),
                QPointF(download_rect.center()),
                QPointF(download_rect.center()),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
            self.assertTrue(delegate.editorEvent(download_event, model, option, index))
            self.assertEqual(delegate._hover_button, "download")
        finally:
            table.deleteLater()

    def test_scan_progress_updates_overlay(self):
        window = MainWindow.__new__(MainWindow)
        overlay_calls: list[tuple[int, int, str, str]] = []
        window.scan_overlay = SimpleNamespace(
            update_progress=lambda current, total, label, status: overlay_calls.append((current, total, label, status))
        )
        window.progress_bar = SimpleNamespace(
            maximum=lambda: 100,
            setRange=lambda *_args: None,
            setValue=lambda *_args: None,
        )
        window.scan_label = SimpleNamespace(setText=lambda *_args: None)
        window.scan_details = SimpleNamespace(setText=lambda *_args: None)

        MainWindow._update_scan_progress(window, 3, 10, "C:/Music/Song.mp3", 1.25)

        self.assertEqual(overlay_calls[-1][0:3], (3, 10, "Song.mp3"))
        self.assertIn("30%", overlay_calls[-1][3])

    def test_open_track_folder_opens_parent_directory(self):
        app_state = simple_app_state()
        widget = TrackListWidget(app_state)
        try:
            with TemporaryDirectory() as tmp:
                audio_path = Path(tmp) / "artist" / "song.mp3"
                audio_path.parent.mkdir()
                track = SimpleNamespace(file_path=str(audio_path))

                with patch("ui.widgets.track_list_widget.get_track_by_id", return_value=track), patch(
                    "ui.widgets.track_list_widget.QDesktopServices.openUrl", return_value=True
                ) as open_url:
                    self.assertTrue(widget._open_track_folder(7))

                open_url.assert_called_once()
                self.assertEqual(Path(open_url.call_args.args[0].toLocalFile()), audio_path.parent)
        finally:
            widget.deleteLater()
            app_state.db.close()

    def test_open_track_folder_ignores_missing_path(self):
        app_state = simple_app_state()
        widget = TrackListWidget(app_state)
        try:
            track = SimpleNamespace(file_path="")
            with patch("ui.widgets.track_list_widget.get_track_by_id", return_value=track), patch(
                "ui.widgets.track_list_widget.QDesktopServices.openUrl"
            ) as open_url:
                self.assertFalse(widget._open_track_folder(7))

            open_url.assert_not_called()
        finally:
            widget.deleteLater()
            app_state.db.close()
