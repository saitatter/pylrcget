from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, call, patch

from PySide6.QtCore import QByteArray, QEvent, QPoint, QPointF, QRect
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QKeyEvent, QKeySequence, QMouseEvent, QPainter, QPalette, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QHeaderView, QPushButton, QSizePolicy, QStyle, QStyleOptionViewItem, QTableView, QWidget

from core.tracklist_models import DownloadState, LyricsState, TrackListRow
from db.database import initialize_database
from ui.delegates.actions_delegate import ActionsDelegate
from ui.library_routes import albums_detail, artists_detail, tracks_album, tracks_all, tracks_artist
from ui.controllers.top_bar_controller import TopBarController
from ui.controllers.navigation_controller import NavigationController
from ui.dialogs.music_folders_dialog import MusicFoldersDialog
from ui.hotkeys import serialize_lyrics_hotkeys
from ui.widgets.hotkey_hints import HotkeyHintManager
from ui.delegates.lyrics_status_delegate import LyricsStatusDelegate
from ui.widgets.lrclib_browser_widget import _BrowserPublishDialog
from ui.widgets.lyrics_editor_widget import LINE_NUMBER_COLUMN, LyricsEditorWidget, TIMESTAMP_MS_ROLE
from ui.dialogs.lyrics_propagate_dialog import HAS_LYRICS_ROLE, LyricsDiffButtonDelegate, LyricsPropagateDialog
from ui.dialogs.lyrics_diff_dialog import _normalized_diff_lines
from ui.widgets.toast import ToastManager
from ui.main_window import MainWindow
from ui.player_bar import PLAYER_COVER_SIZE, PlayerBar
from ui.theme_tokens import get_theme_tokens
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

    def test_track_metadata_delegate_handles_links_in_track_column(self):
        app_state = simple_app_state()
        widget = TrackListWidget(app_state)
        opened_albums: list[int] = []
        try:
            widget.openAlbum.connect(opened_albums.append)
            widget.model.set_rows(
                [
                    TrackListRow(
                        track_id=1,
                        title="Song",
                        artist="Radiohead",
                        artist_id=7,
                        album="Kid A",
                        album_id=11,
                        track_number=1,
                        duration_s=120,
                        lyrics_state=LyricsState.SYNCED,
                    )
                ]
            )
            widget.resize(900, 260)
            widget.show()
            self.app.processEvents()

            track_index = widget.model.index(0, 1)
            rect = widget.table.visualRect(track_index)
            option = QStyleOptionViewItem()
            option.widget = widget.table
            option.rect = rect
            option.font = widget.table.font()

            content = rect.adjusted(10, 6, -10, -6)
            meta_font = QFont(option.font)
            meta_font.setPointSize(max(meta_font.pointSize() - 1, 9))
            metrics = QFontMetrics(meta_font)
            meta_rect = QRect(content.left(), content.bottom() - metrics.height(), content.width(), metrics.height())
            _, _, _, album_rect, _ = widget.track_info._metadata_layout(
                meta_rect,
                metrics,
                widget.model._rows[0],
            )
            pos = album_rect.center()
            release = QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                QPointF(pos),
                QPointF(pos),
                QPointF(widget.table.viewport().mapToGlobal(pos)),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )

            self.assertTrue(widget.track_info.editorEvent(release, widget.model, option, track_index))
            self.assertEqual(opened_albums, [11])
            self.assertFalse(widget.track_info.editorEvent(release, widget.model, option, widget.model.index(0, 0)))
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

    def test_synced_lyrics_table_can_copy_selected_lrc_rows(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_synced([(1200, "First line"), (3000, "Second line")])
            widget.table.selectRow(1)

            widget._copy_synced_selection_to_clipboard()

            self.assertEqual(self.app.clipboard().text(), "[00:03.00] Second line")
        finally:
            widget.deleteLater()

    def test_synced_lyrics_table_can_paste_lrc_from_clipboard(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_synced([(1200, "Old line")])
            self.app.clipboard().setText("[00:02.50] New line\n[00:04.00] Next line")

            self.assertTrue(widget._paste_synced_from_clipboard())

            self.assertEqual(widget.table.rowCount(), 2)
            self.assertEqual(widget.table.item(0, 0).text(), "00:02.50")
            self.assertEqual(widget.table.item(0, 1).text(), "New line")
            self.assertEqual(widget.table.item(1, 0).text(), "00:04.00")
            self.assertEqual(widget.table.item(1, 1).text(), "Next line")
        finally:
            widget.deleteLater()

    def test_lyrics_quick_actions_have_shortcuts(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_synced([(1200, "First line"), (3000, "Second line"), (8000, "")])
            widget.table.selectRow(0)

            self.assertIn("(Left)", widget.btn_shift_minus.toolTip())
            self.assertIn("(Right)", widget.btn_shift_plus.toolTip())
            self.assertEqual(widget._shortcut_shift_minus.key().toString(), "Left")
            self.assertEqual(widget._shortcut_shift_plus.key().toString(), "Right")
            self.assertEqual(widget._shortcut_snap.key().toString(), "Ctrl+Return")
            self.assertEqual(widget._shortcut_add_line.key().toString(), "Ins")
            self.assertEqual(widget._shortcut_add_line_new.key().toString(), "Ctrl+N")
            self.assertEqual(widget._shortcut_add_line_before.key().toString(), "Ctrl+Shift+N")
            self.assertEqual(widget._shortcut_delete_line.key().toString(), "Del")
            self.assertIs(widget._shortcut_shift_plus.parent(), widget.table)

            widget._shortcut_shift_plus.activated.emit()
            self.assertEqual(widget.table.item(0, 0).text(), "00:01.30")
            self.assertEqual(widget.table.item(0, 0).data(TIMESTAMP_MS_ROLE), 1300)
        finally:
            widget.deleteLater()

    def test_lyrics_hotkey_bindings_update_configurable_shortcuts(self):
        widget = LyricsEditorWidget()
        try:
            widget.set_hotkey_bindings(
                {
                    "snap": "Tab",
                    "shift_selected": "Alt+S",
                    "shift_all_from_first": "Ctrl+Alt+A",
                }
            )

            self.assertEqual(widget.lyrics_hotkeys["snap"], "Tab")
            self.assertEqual(widget._shortcut_snap.key().toString(), "Tab")
            self.assertIsNone(widget._shortcut_snap_enter)
            self.assertEqual(widget._shortcut_shift_selected.key().toString(), "Alt+S")
            self.assertIsNone(widget._shortcut_shift_selected_enter)
            self.assertEqual(widget._shortcut_shift_all.key().toString(), "Ctrl+Alt+A")
            self.assertIsNone(widget._shortcut_shift_all_enter)
            self.assertIn("(Tab)", widget.btn_snap.toolTip())
            self.assertIn("(Alt+S)", widget.btn_shift_selected.toolTip())
            self.assertIn("(Ctrl+Alt+A)", widget.btn_shift_all_from_first.toolTip())
        finally:
            widget.deleteLater()

    def test_lyrics_hotkey_bindings_can_disable_shortcuts(self):
        widget = LyricsEditorWidget()
        try:
            widget.set_hotkey_bindings(
                {
                    "snap": {"enabled": False, "key": "Tab"},
                    "shift_selected": {"enabled": True, "key": "Alt+S"},
                    "shift_all_from_first": {"enabled": True, "key": "Ctrl+Alt+A"},
                }
            )

            self.assertEqual(widget.lyrics_hotkeys["snap"], "")
            self.assertIsNone(widget._shortcut_snap)
            self.assertIsNone(widget._shortcut_snap_enter)
            self.assertIn("(Disabled)", widget.btn_snap.toolTip())
        finally:
            widget.deleteLater()

    def test_insert_line_before_selection_can_add_first_row(self):
        widget = LyricsEditorWidget()
        try:
            widget.set_current_position_provider(lambda: 500)
            widget._set_synced([(1200, "First line"), (3000, "Second line")])
            widget.table.setCurrentCell(0, 1)

            widget._add_line_before_selection()

            self.assertEqual(widget.table.rowCount(), 3)
            self.assertEqual(widget.table.item(0, 0).text(), "00:00.50")
            self.assertEqual(widget.table.item(0, 1).text(), "")
            self.assertEqual(widget.table.currentRow(), 0)
            self.assertEqual(widget.table.currentColumn(), 1)
            self.assertEqual(widget.table.item(1, 1).text(), "First line")
        finally:
            widget.deleteLater()

    def test_enter_on_synced_timestamp_starts_editing_without_seek(self):
        widget = LyricsEditorWidget()
        emitted: list[int] = []
        widget.seekRequested.connect(emitted.append)
        try:
            widget._set_synced([(1200, "First line"), (3000, "Second line")])
            widget.table.setCurrentCell(0, 0)

            self.assertTrue(widget._handle_synced_table_enter())

            self.assertEqual(emitted, [])
            self.assertEqual(widget.table.state(), widget.table.State.EditingState)
        finally:
            widget.deleteLater()

    def test_enter_on_synced_lyric_replays_from_line_timestamp(self):
        widget = LyricsEditorWidget()
        emitted: list[int] = []
        widget.seekRequested.connect(emitted.append)
        try:
            widget._set_synced([(1200, "First line"), (3000, "Second line")])
            widget.table.setCurrentCell(1, 1)

            self.assertTrue(widget._handle_synced_table_enter())

            self.assertEqual(emitted, [3000])
        finally:
            widget.deleteLater()

    def test_keypad_enter_on_synced_lyric_replays_from_line_timestamp(self):
        widget = LyricsEditorWidget()
        emitted: list[int] = []
        widget.seekRequested.connect(emitted.append)
        try:
            widget._set_synced([(1200, "First line"), (3000, "Second line")])
            widget.table.setCurrentCell(1, 1)
            event = QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_Enter,
                Qt.KeyboardModifier.KeypadModifier,
            )

            self.assertTrue(widget.eventFilter(widget.table, event))

            self.assertEqual(emitted, [3000])
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

    def test_synced_lyrics_editor_marks_duplicate_timestamps_invalid(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_synced([(1200, "First line"), (1200, "Second line"), (5000, "")])

            self.assertFalse(widget.btn_save.isEnabled())
            self.assertTrue(widget.btn_autofix.isEnabled())
            self.assertEqual(widget._lint_rows, {0, 1})
            self.assertIn("Duplicate timestamp", widget.validation_hint.text())
            self.assertEqual(widget.validation_badge.text(), "2 issues")
            self.assertIn("Duplicate timestamp", widget.table.item(0, 0).toolTip())
            self.assertIn("Duplicate timestamp", widget.table.item(1, 1).toolTip())
            self.assertEqual(widget.table.item(0, 0).background().color(), QColor("#2a0a0a"))
            self.assertEqual(widget.table.item(1, 1).background().color(), QColor("#2a0a0a"))
            self.assertNotEqual(widget.table.item(0, LINE_NUMBER_COLUMN).background().color(), QColor("#2a0a0a"))
            self.assertEqual(widget.table.item(0, LINE_NUMBER_COLUMN).foreground().color(), QColor("#fee2e2"))
        finally:
            widget.deleteLater()

    def test_validation_hint_click_jumps_to_first_issue(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_synced([(3000, "Second line"), (2000, "First line"), (5000, "")])
            event = QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                QPointF(1, 1),
                QPointF(1, 1),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )

            self.assertTrue(widget.eventFilter(widget.validation_hint, event))

            self.assertEqual(widget.table.currentRow(), 1)
            self.assertEqual(widget.table.currentColumn(), 0)
        finally:
            widget.deleteLater()

    def test_synced_duplicate_autofix_separates_timestamps(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_synced([(1200, "First line"), (1200, "Second line"), (5000, "")])

            widget._autofix_validation_problems()

            self.assertTrue(widget.btn_save.isEnabled())
            self.assertEqual(widget.table.item(0, 0).text(), "00:01.20")
            self.assertEqual(widget.table.item(1, 0).text(), "00:01.25")
            self.assertEqual(widget.validation_badge.text(), "Valid")
        finally:
            widget.deleteLater()

    def test_publish_buttons_follow_synced_validator_state(self):
        widget = LyricsEditorWidget()
        try:
            widget.set_track_lyrics(
                "Song",
                "First line\nSecond line",
                "[00:01.20] First line\n[00:01.20] Second line\n[00:05.00]",
                False,
            )

            self.assertFalse(widget.btn_save.isEnabled())
            self.assertFalse(widget.btn_publish_synced.isEnabled())
            self.assertFalse(widget.btn_publish_plain.isEnabled())
            self.assertEqual(widget.btn_publish_synced.toolTip(), "Fix validation issues before publishing.")
            self.assertEqual(widget.btn_publish_plain.toolTip(), "Fix validation issues before publishing.")

            widget.set_track_lyrics(
                "Song",
                "First line\nSecond line",
                "[00:01.20] First line\n[00:03.00] Second line\n[00:05.00]",
                False,
            )

            self.assertTrue(widget.btn_save.isEnabled())
            self.assertTrue(widget.btn_publish_synced.isEnabled())
            self.assertTrue(widget.btn_publish_plain.isEnabled())
            self.assertEqual(widget.btn_publish_synced.toolTip(), "Publish synced (LRC) lyrics to LRCLIB")
            self.assertEqual(widget.validation_badge.text(), "Valid")
        finally:
            widget.deleteLater()

    def test_publish_buttons_explain_dirty_draft_state(self):
        widget = LyricsEditorWidget()
        try:
            widget.set_track_lyrics(
                "Song",
                "Saved line",
                "[00:01.20] Saved line\n[00:05.00]",
                False,
                dirty_txt_lyrics="Draft line",
                dirty_lrc_lyrics="[00:01.20] Draft line\n[00:05.00]",
                dirty_lyrics_present=True,
            )

            self.assertFalse(widget.btn_publish_synced.isEnabled())
            self.assertFalse(widget.btn_publish_plain.isEnabled())
            self.assertEqual(widget.btn_publish_synced.toolTip(), "Save the draft before publishing to LRCLIB.")
            self.assertEqual(widget.btn_publish_plain.toolTip(), "Save the draft before publishing to LRCLIB.")
        finally:
            widget.deleteLater()

    def test_publish_buttons_disable_when_saved_lyrics_become_dirty(self):
        widget = LyricsEditorWidget()
        try:
            widget.set_track_lyrics(
                "Song",
                "Saved line",
                "[00:01.20] Saved line\n[00:05.00]",
                False,
            )

            self.assertTrue(widget.btn_publish_synced.isEnabled())
            self.assertTrue(widget.btn_publish_plain.isEnabled())

            widget.table.item(0, 1).setText("Changed line")

            self.assertTrue(widget._has_dirty_draft)
            self.assertFalse(widget.btn_publish_synced.isEnabled())
            self.assertFalse(widget.btn_publish_plain.isEnabled())
            self.assertEqual(widget.btn_publish_synced.toolTip(), "Save the draft before publishing to LRCLIB.")
            self.assertEqual(widget.btn_publish_plain.toolTip(), "Save the draft before publishing to LRCLIB.")
        finally:
            widget.deleteLater()

    def test_publish_plain_button_follows_plain_validator_state(self):
        widget = LyricsEditorWidget()
        try:
            widget.set_track_lyrics("Song", "[00:01.00] Not plain", "", False)

            self.assertFalse(widget.btn_save.isEnabled())
            self.assertFalse(widget.btn_publish_plain.isEnabled())

            widget.set_track_lyrics("Song", "Plain line", "", False)

            self.assertTrue(widget.btn_save.isEnabled())
            self.assertTrue(widget.btn_publish_plain.isEnabled())
        finally:
            widget.deleteLater()

    def test_synced_lyrics_editor_shows_line_numbers(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_synced([(1200, "First line"), (3000, "Second line")])

            self.assertTrue(widget.table.verticalHeader().isHidden())
            self.assertEqual(widget.table.horizontalHeaderItem(LINE_NUMBER_COLUMN).text(), "#")
            self.assertEqual(widget.table.item(0, LINE_NUMBER_COLUMN).text(), "1")
            self.assertEqual(widget.table.item(1, LINE_NUMBER_COLUMN).text(), "2")

            widget.table.setCurrentCell(0, 1)
            widget._add_line_before_selection()
            self.assertEqual(
                [widget.table.item(row, LINE_NUMBER_COLUMN).text() for row in range(widget.table.rowCount())],
                ["1", "2", "3"],
            )
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

    def test_sync_others_button_emits_current_lyrics(self):
        widget = LyricsEditorWidget()
        emitted: list[tuple[str, str]] = []
        widget.propagateRequested.connect(lambda lrc, plain: emitted.append((lrc, plain)))
        try:
            widget._set_synced([(1200, "First line"), (3000, "Second line"), (8000, "")])

            self.assertTrue(widget.btn_sync_others.isEnabled())
            widget._emit_propagate()

            self.assertEqual(len(emitted), 1)
            self.assertIn("[00:01.20] First line", emitted[0][0])
            self.assertEqual(emitted[0][1], "First line\nSecond line")
        finally:
            widget.deleteLater()

    def test_propagate_dialog_returns_checked_track_ids(self):
        from db.models import Track

        track = Track(
            id=42,
            file_path="song.flac",
            file_name="song.flac",
            title="Song",
            album_name="Single",
            album_artist_name="Artist A",
            album_id=2,
            artist_name="Artist A",
            artist_id=1,
            image_path=None,
            track_number=1,
            txt_lyrics="old lyrics",
            lrc_lyrics=None,
            duration=181.0,
            instrumental=False,
        )
        dialog = LyricsPropagateDialog(
            [
                {
                    "track": track,
                    "score": 96,
                    "title_score": 100,
                    "artist_score": 100,
                    "duration_score": 92,
                }
            ],
            source_lyrics="new lyrics",
        )
        try:
            headers = [dialog.table.horizontalHeaderItem(index).text() for index in range(dialog.table.columnCount())]
            self.assertEqual(headers, ["Apply", "Track", "Artist", "Album", "Duration", "Match", "Diff"])
            self.assertNotIn("Title", headers)
            self.assertNotIn("Artist/Time", headers)
            self.assertEqual(dialog.table.objectName(), "LyricsSyncTable")
            self.assertTrue(dialog.table.alternatingRowColors())
            self.assertFalse(dialog.table.showGrid())
            self.assertIsNone(dialog.table.cellWidget(0, 6))
            delegate = dialog.table.itemDelegateForColumn(6)
            self.assertIsInstance(delegate, LyricsDiffButtonDelegate)
            index = dialog.table.model().index(0, 6)
            self.assertTrue(index.data(HAS_LYRICS_ROLE))
            self.assertEqual(dialog.selected_track_ids(), [42])
        finally:
            dialog.deleteLater()

    def test_lyrics_diff_ignores_trailing_whitespace(self):
        self.assertEqual(
            _normalized_diff_lines("[00:01.00] Same line   \n[00:02.00] Next"),
            _normalized_diff_lines("[00:01.00] Same line\n[00:02.00] Next   "),
        )

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
            self.assertEqual(widget.model.columnCount(), 5)
            self.assertEqual(widget.model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole), "#")
            self.assertEqual(widget.model.headerData(3, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole), "Lyrics")
            self.assertEqual(
                widget.model.headerData(3, Qt.Orientation.Horizontal, Qt.ItemDataRole.TextAlignmentRole),
                int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter),
            )
            self.assertFalse(widget.table.isColumnHidden(0))
            self.assertFalse(widget.table.isColumnHidden(3))
            self.assertGreaterEqual(widget.table.columnWidth(0), 50)
            self.assertGreaterEqual(widget.table.columnWidth(2), 90)
            self.assertEqual(widget.header.sectionResizeMode(3), QHeaderView.ResizeMode.Fixed)
            self.assertGreaterEqual(widget.table.columnWidth(3), 100)
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

    def test_light_theme_disabled_controls_keep_readable_contrast(self):
        tokens = get_theme_tokens("LightTheme")
        self.assertEqual(tokens["color-disabled-text"], "#475569")
        app_stylesheet = Path("src/ui/qss/app.qss").read_text(encoding="utf-8")
        main_stylesheet = Path("src/ui/qss/main_window.qss").read_text(encoding="utf-8")
        player_stylesheet = Path("src/ui/qss/player_bar.qss").read_text(encoding="utf-8")
        self.assertIn("QToolButton:disabled", app_stylesheet)
        self.assertIn("QToolButton#TopBarAction:disabled", main_stylesheet)
        self.assertIn("QToolButton:disabled", player_stylesheet)

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

    def test_hotkey_badge_refresh_updates_after_layout_shift(self):
        parent = QWidget()
        button = QPushButton(parent)
        button.setGeometry(10, 10, 80, 36)
        manager = HotkeyHintManager(parent)
        try:
            parent.resize(220, 120)
            parent.show()
            self.app.processEvents()
            manager.register(button, "Ctrl+F")
            manager.set_visible(True)
            original_pos = manager._hints[0].badge.pos()

            button.move(10, 70)
            manager.refresh_positions()

            self.assertNotEqual(manager._hints[0].badge.pos(), original_pos)
            self.assertGreater(manager._hints[0].badge.y(), original_pos.y())
            self.assertTrue(manager._hints[0].badge.isVisible())
        finally:
            parent.deleteLater()

    def test_hotkey_badge_register_updates_existing_widget(self):
        parent = QWidget()
        button = QPushButton(parent)
        manager = HotkeyHintManager(parent)
        try:
            manager.register(button, "Ctrl+F")
            manager.register(button, "Tab")

            self.assertEqual(len(manager._hints), 1)
            self.assertEqual(manager._hints[0].key, "Tab")
            self.assertEqual(manager._hints[0].badge.text(), "Tab")
        finally:
            parent.deleteLater()

    def test_player_speed_label_and_value_fit_centered(self):
        widget = PlayerBar(player=None)
        try:
            widget.cmb_speed.resize(100, 28)
            widget._set_speed_combo_value(1.0)
            prefix = widget.lbl_speed_prefix.geometry()
            margins = widget.cmb_speed.lineEdit().textMargins()
            value_width = widget.cmb_speed.lineEdit().fontMetrics().horizontalAdvance(widget.cmb_speed.lineEdit().text())
            group_left = prefix.left()
            group_width = 44 + 4 + 50
            group_right = group_left + group_width

            self.assertGreaterEqual(group_left, 0)
            self.assertLessEqual(group_right, widget.cmb_speed.width())
            self.assertGreaterEqual(group_left - (widget.cmb_speed.width() - group_right), 0)
            self.assertLessEqual(group_left - (widget.cmb_speed.width() - group_right), 10)
            self.assertLessEqual(margins.left() + value_width, group_right)

            left_for_one_decimal = widget.lbl_speed_prefix.x()
            margin_for_one_decimal = margins.left()
            widget._set_speed_combo_value(1.05)
            self.assertEqual(widget.lbl_speed_prefix.x(), left_for_one_decimal)
            self.assertEqual(widget.cmb_speed.lineEdit().textMargins().left(), margin_for_one_decimal)
        finally:
            widget.deleteLater()

    def test_player_cover_is_larger_and_text_is_centered(self):
        widget = PlayerBar(player=None)
        try:
            widget.resize(1000, 120)
            widget.show()
            self.app.processEvents()

            self.assertEqual(widget.lbl_cover.width(), PLAYER_COVER_SIZE)
            self.assertEqual(widget.lbl_cover.height(), PLAYER_COVER_SIZE)

            text_widgets = [widget.lbl_title, widget.lbl_artist, widget.lbl_album]
            text_top = min(label.geometry().top() for label in text_widgets if label.isVisible())
            text_bottom = max(label.geometry().bottom() for label in text_widgets if label.isVisible())
            text_center_y = (text_top + text_bottom) // 2
            cover_center_y = widget.lbl_cover.geometry().center().y()

            self.assertLessEqual(abs(text_center_y - cover_center_y), 4)
        finally:
            widget.deleteLater()

    def test_player_volume_slider_aligns_with_speed_combo(self):
        widget = PlayerBar(player=None)
        try:
            widget.show()
            self.app.processEvents()

            self.assertEqual(widget.slider_volume.width(), widget.cmb_speed.width())
            self.assertEqual(widget.slider_volume.x(), widget.cmb_speed.x())
            self.assertEqual(widget.lbl_volume.x(), widget.btn_speed_down.x())
            self.assertEqual(widget.lbl_volume_value.x(), widget.btn_speed_up.x())
            self.assertEqual(widget.lbl_volume_value.width(), widget.btn_speed_up.width())
        finally:
            widget.deleteLater()

    def test_track_action_buttons_track_individual_hover(self):
        table = QTableView()
        model = QStandardItemModel(1, 5)
        item = QStandardItem("")
        item.setData(
            TrackListRow(
                track_id=1,
                title="Song",
                artist="Artist",
                artist_id=None,
                album="Album",
                album_id=None,
                track_number=1,
                duration_s=120,
                lyrics_state=LyricsState.NONE,
                download_state=DownloadState.IDLE,
            ),
            Qt.ItemDataRole.UserRole,
        )
        model.setItem(0, 4, item)
        table.setModel(model)
        delegate = ActionsDelegate(table)
        option = QStyleOptionViewItem()
        option.widget = table
        option.rect = QRect(0, 0, 150, 44)
        refresh_rect, download_rect = delegate._button_rects(option.rect)
        index = model.index(0, 4)
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

    def test_track_action_buttons_keep_theme_background_when_row_selected(self):
        table = QTableView()
        model = QStandardItemModel(1, 5)
        item = QStandardItem("")
        item.setData(
            TrackListRow(
                track_id=1,
                title="Song",
                artist="Artist",
                artist_id=None,
                album="Album",
                album_id=None,
                track_number=1,
                duration_s=120,
                lyrics_state=LyricsState.SYNCED,
                download_state=DownloadState.IDLE,
            ),
            Qt.ItemDataRole.UserRole,
        )
        model.setItem(0, 4, item)
        table.setModel(model)
        delegate = ActionsDelegate(table)
        option = QStyleOptionViewItem()
        option.widget = table
        option.rect = QRect(0, 0, 150, 44)
        option.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Selected
        index = model.index(0, 4)
        refresh_rect, download_rect = delegate._button_rects(option.rect)
        image = QImage(option.rect.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor("#554872"))
        painter = QPainter(image)
        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()
            table.deleteLater()

        button_sample = image.pixelColor(download_rect.left() + 8, download_rect.center().y())
        row_sample = image.pixelColor(8, download_rect.center().y())
        self.assertNotEqual(row_sample.name(), "#000000")
        self.assertLess(abs(button_sample.value() - row_sample.value()), 8)

        image.fill(QColor("#554872"))
        delegate._hover_row = 0
        delegate._hover_button = "download"
        painter = QPainter(image)
        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()

        hover_button_sample = image.pixelColor(download_rect.left() + 8, download_rect.center().y())
        hover_row_sample = image.pixelColor(8, download_rect.center().y())
        hover_cell_background = image.pixelColor(refresh_rect.left() - 4, download_rect.center().y())
        self.assertGreater(hover_button_sample.value(), hover_row_sample.value())
        self.assertLess(abs(hover_cell_background.value() - hover_row_sample.value()), 8)

    def test_lyrics_status_delegate_preserves_status_color_when_row_selected(self):
        table = QTableView()
        model = QStandardItemModel(1, 5)
        item = QStandardItem("Synced")
        synced_color = QColor("#22c55e")
        item.setData(synced_color, Qt.ItemDataRole.ForegroundRole)
        model.setItem(0, 3, item)
        table.setModel(model)
        delegate = LyricsStatusDelegate(table)
        option = QStyleOptionViewItem()
        option.widget = table
        option.rect = QRect(0, 0, 118, 44)
        option.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Selected
        option.palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))

        try:
            delegate.initStyleOption(option, model.index(0, 3))
        finally:
            table.deleteLater()

        highlighted = option.palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.HighlightedText)
        self.assertEqual(highlighted.name(), synced_color.name())

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

    def test_status_message_uses_toast_area_without_changing_layout(self):
        window = MainWindow.__new__(MainWindow)
        window.central_widget = QWidget()
        window.central_widget.resize(480, 320)
        window.central_widget.show()
        window.player_bar = QWidget(window.central_widget)
        window.player_bar.setGeometry(0, 260, 480, 52)
        window.player_bar.show()
        window.toasts = ToastManager(window.central_widget)
        window.toasts.set_bottom_anchor(window.player_bar)
        try:
            before = window.central_widget.geometry()

            MainWindow._show_status_message(window, "Lyrics saved.", 2500)
            self.app.processEvents()

            self.assertEqual(window.central_widget.geometry(), before)
            self.assertIsNotNone(window.toasts._status_toast)
            toast = window.toasts._status_toast
            self.assertTrue(toast.isVisible())
            self.assertEqual(toast.lbl.text(), "Lyrics saved.")
            self.assertLessEqual(
                toast.y() + toast.height(),
                window.player_bar.y(),
            )

            window.toasts.show_toast("Saved.", "success", 3000)
            self.app.processEvents()
            normal_toast = next(t for t in window.toasts._toasts if t is not toast)
            self.assertLess(normal_toast.y(), toast.y())
            self.assertLessEqual(normal_toast.y() + normal_toast.height(), toast.y())
        finally:
            window.central_widget.deleteLater()

    def test_status_and_toast_with_same_text_do_not_duplicate(self):
        host = QWidget()
        host.resize(480, 320)
        host.show()
        manager = ToastManager(host)
        try:
            manager.show_status("Lyrics saved.", 2500)
            manager.show_toast("Lyrics saved.", "success", 3000)
            self.app.processEvents()

            self.assertEqual(len(manager._toasts), 1)
            self.assertIsNone(manager._status_toast)
            self.assertEqual(manager._toasts[0].lbl.text(), "Lyrics saved.")

            manager.show_status("Lyrics saved.", 2500)
            self.app.processEvents()
            self.assertEqual(len(manager._toasts), 1)
        finally:
            host.deleteLater()

    def test_enter_play_handler_uses_the_focused_track_list(self):
        window = MainWindow.__new__(MainWindow)
        played: list[int] = []
        window.on_play_track = lambda track_id: played.append(int(track_id))
        track_list = SimpleNamespace(selected_track_id=lambda: 42)

        MainWindow._play_selected_from_track_list(window, track_list)

        self.assertEqual(played, [42])

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


@unittest.skipUnless(HAS_QT, "PySide6 is required for widget tests")
class MainWindowInstrumentalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_app()

    def test_mark_instrumental_refreshes_active_album_track_list(self):
        window = MainWindow.__new__(MainWindow)
        album_track_list = SimpleNamespace(restore_selection=MagicMock())
        album_stack = SimpleNamespace(currentWidget=lambda: album_track_list)

        window.tracks_tab = object()
        window.albums_page = object()
        window.artists_page = object()
        window.tabs = SimpleNamespace(currentWidget=lambda: window.albums_page)
        window.track_list = SimpleNamespace()
        window.albums_tab = SimpleNamespace(
            stack=album_stack,
            track_list=album_track_list,
        )
        window.artists_tab = SimpleNamespace(
            stack=SimpleNamespace(currentWidget=lambda: object()),
            album_browser=SimpleNamespace(),
        )
        window.app_state = SimpleNamespace(db=object())
        window._confirm_bulk = MagicMock(return_value=True)
        window._show_status_message = MagicMock()
        window._refresh_visible_library_view_after_downloads = MagicMock()
        window._publish_instrumental_to_lrclib = MagicMock()
        window.top_bar = SimpleNamespace(filter_values=lambda: {"instrumental": False})

        with patch("ui.main_window.mark_tracks_instrumental") as mark_tracks:
            MainWindow._on_mark_instrumental(window, [1, 2, None])

        mark_tracks.assert_called_once_with(window.app_state.db, [1, 2])
        window._refresh_visible_library_view_after_downloads.assert_called_once_with()
        album_track_list.restore_selection.assert_called_once_with({1, 2})
        window._show_status_message.assert_called_once_with(
            "Marked 2 track(s) as instrumental. Enable the Instrumental filter to show them.",
            5000,
        )
        window._publish_instrumental_to_lrclib.assert_called_once_with([1, 2])

    def test_apply_track_filters_updates_embedded_album_and_artist_track_lists(self):
        window = MainWindow.__new__(MainWindow)
        main_track_list = SimpleNamespace(
            setSearchValue=MagicMock(),
            setFilters=MagicMock(),
            set_now_playing=MagicMock(),
        )
        album_track_list = SimpleNamespace(
            setSearchValue=MagicMock(),
            setFilters=MagicMock(),
            set_now_playing=MagicMock(),
        )
        artist_track_list = SimpleNamespace(
            setSearchValue=MagicMock(),
            setFilters=MagicMock(),
            set_now_playing=MagicMock(),
        )
        window.track_list = main_track_list
        window.albums_tab = SimpleNamespace(track_list=album_track_list)
        window.artists_tab = SimpleNamespace(album_browser=SimpleNamespace(track_list=artist_track_list))
        window.top_bar = SimpleNamespace(
            search_text=lambda: "downfall",
            filter_values=lambda: {
                "synced": True,
                "plain": True,
                "instrumental": True,
                "none": True,
                "unsaved": False,
            },
        )
        window.app_state = SimpleNamespace(player=None)
        window._update_search_feedback = MagicMock()

        MainWindow._apply_track_filters(window)

        for track_list in (main_track_list, album_track_list, artist_track_list):
            track_list.setSearchValue.assert_called_once_with("downfall")
            track_list.setFilters.assert_called_once_with(
                synced=True,
                plain=True,
                instrumental=True,
                none_=True,
                unsaved=False,
            )
            track_list.set_now_playing.assert_not_called()
        window._update_search_feedback.assert_called_once_with()

    def test_selected_track_ids_for_toolbar_uses_active_track_list(self):
        window = MainWindow.__new__(MainWindow)
        active_track_list = SimpleNamespace(selected_track_ids=lambda: [5, 7])
        window.track_list = SimpleNamespace()
        window._active_track_list_widget = MagicMock(return_value=active_track_list)

        self.assertEqual(MainWindow._selected_track_ids_for_toolbar(window), [5, 7])

    def test_update_selection_actions_bar_shows_only_active_bar(self):
        window = MainWindow.__new__(MainWindow)
        active_track_list = SimpleNamespace()
        inactive_track_list_a = SimpleNamespace()
        inactive_track_list_b = SimpleNamespace()

        active_bar = SimpleNamespace(setVisible=MagicMock())
        inactive_bar_a = SimpleNamespace(setVisible=MagicMock())
        inactive_bar_b = SimpleNamespace(setVisible=MagicMock())
        active_label = SimpleNamespace(setText=MagicMock())
        inactive_label_a = SimpleNamespace(setText=MagicMock())
        inactive_label_b = SimpleNamespace(setText=MagicMock())
        active_button = SimpleNamespace(setEnabled=MagicMock())
        inactive_button_a = SimpleNamespace(setEnabled=MagicMock())
        inactive_button_b = SimpleNamespace(setEnabled=MagicMock())

        window.selection_actions_bar = active_bar
        window.selection_actions_label = active_label
        window.selection_action_buttons = [active_button]
        window.albums_selection_actions_bar = inactive_bar_a
        window.albums_selection_actions_label = inactive_label_a
        window.albums_selection_action_buttons = [inactive_button_a]
        window.artists_selection_actions_bar = inactive_bar_b
        window.artists_selection_actions_label = inactive_label_b
        window.artists_selection_action_buttons = [inactive_button_b]
        window.track_list = active_track_list
        window.albums_tab = SimpleNamespace(track_list=inactive_track_list_a)
        window.artists_tab = SimpleNamespace(album_browser=SimpleNamespace(track_list=inactive_track_list_b))
        window._active_track_list_widget = MagicMock(return_value=active_track_list)
        window._selected_track_ids_for_toolbar = MagicMock(return_value=[11, 12])

        MainWindow._update_selection_actions_bar(window)

        active_bar.setVisible.assert_called_once_with(True)
        inactive_bar_a.setVisible.assert_called_once_with(False)
        inactive_bar_b.setVisible.assert_called_once_with(False)
        active_label.setText.assert_called_once_with("Selected tracks: 2")
        active_button.setEnabled.assert_called_once_with(True)
        inactive_label_a.setText.assert_not_called()
        inactive_label_b.setText.assert_not_called()
        inactive_button_a.setEnabled.assert_not_called()
        inactive_button_b.setEnabled.assert_not_called()

    def test_create_selection_actions_bar_has_fixed_vertical_size(self):
        window = MainWindow.__new__(MainWindow)

        bar, _label, _buttons = MainWindow._create_selection_actions_bar(window)

        try:
            self.assertEqual(bar.sizePolicy().verticalPolicy(), QSizePolicy.Policy.Fixed)
            self.assertEqual(bar.maximumHeight(), 44)
        finally:
            bar.deleteLater()

    def test_save_window_state_persists_filter_checkboxes(self):
        window = MainWindow.__new__(MainWindow)
        saved_payload = {}
        window._persist_window_state_payload = lambda payload: saved_payload.update(payload)
        window.saveGeometry = MagicMock(return_value=QByteArray(b"geo"))
        window.tabs = SimpleNamespace(currentIndex=lambda: 2)
        window.top_bar = SimpleNamespace(
            search_text=lambda: "chapter ii",
            filter_values=lambda: {
                "synced": False,
                "plain": True,
                "instrumental": True,
                "none": False,
                "unsaved": True,
            }
        )

        MainWindow._save_window_state(window)

        self.assertEqual(saved_payload["search_text"], "chapter ii")
        self.assertEqual(saved_payload["filters"]["synced"], False)
        self.assertEqual(saved_payload["filters"]["plain"], True)
        self.assertEqual(saved_payload["filters"]["instrumental"], True)
        self.assertEqual(saved_payload["filters"]["none"], False)
        self.assertEqual(saved_payload["filters"]["unsaved"], True)
        self.assertEqual(saved_payload["tab_index"], 2)
        self.assertTrue(isinstance(saved_payload["geometry"], str) and saved_payload["geometry"])

    def test_restore_window_state_restores_filter_checkboxes(self):
        window = MainWindow.__new__(MainWindow)
        window._load_window_state_payload = MagicMock(
            return_value={
                "search_text": "downfall",
                "filters": {
                    "synced": False,
                    "plain": True,
                    "instrumental": True,
                    "none": False,
                    "unsaved": True,
                },
            }
        )
        window.top_bar = SimpleNamespace(
            default_filter_values=lambda: {
                "synced": True,
                "plain": True,
                "instrumental": False,
                "none": True,
                "unsaved": False,
            },
            set_search_text=MagicMock(),
            set_filter_values=MagicMock(),
        )
        window._apply_track_filters = MagicMock()
        window.tabs = SimpleNamespace(count=lambda: 5, setCurrentIndex=MagicMock())

        MainWindow._restore_window_state(window)

        window.top_bar.set_search_text.assert_called_once_with("downfall")
        window.top_bar.set_filter_values.assert_called_once_with(
            {
                "synced": False,
                "plain": True,
                "instrumental": True,
                "none": False,
                "unsaved": True,
            }
        )
        window._apply_track_filters.assert_called_once_with()

    def test_apply_hotkey_preferences_updates_lyrics_views_and_hints(self):
        window = MainWindow.__new__(MainWindow)
        lyrics_view = SimpleNamespace(
            btn_snap=object(),
            btn_shift_selected=object(),
            btn_shift_all_from_first=object(),
            set_hotkey_bindings=MagicMock(),
        )
        albums_view = SimpleNamespace(
            btn_snap=object(),
            btn_shift_selected=object(),
            btn_shift_all_from_first=object(),
            set_hotkey_bindings=MagicMock(),
        )
        artists_view = SimpleNamespace(
            btn_snap=object(),
            btn_shift_selected=object(),
            btn_shift_all_from_first=object(),
            set_hotkey_bindings=MagicMock(),
        )
        window.lyrics_view = lyrics_view
        window.albums_lyrics_view = albums_view
        window.artists_lyrics_view = artists_view
        window.hotkey_hints = SimpleNamespace(refresh_positions=MagicMock())
        window._apply_global_shortcuts = MagicMock()
        window._register_hotkey_hints = MagicMock()

        MainWindow._apply_hotkey_preferences(
            window,
            SimpleNamespace(
                hotkey_bindings_json=serialize_lyrics_hotkeys(
                    {
                        "snap": "Tab",
                        "shift_selected": "Alt+S",
                        "shift_all_from_first": "Ctrl+Alt+A",
                    }
                )
            ),
        )

        expected = {
            "snap": {"enabled": True, "key": "Tab"},
            "shift_selected": {"enabled": True, "key": "Alt+S"},
            "shift_all_from_first": {"enabled": True, "key": "Ctrl+Alt+A"},
        }
        lyrics_view.set_hotkey_bindings.assert_called_once_with(expected)
        albums_view.set_hotkey_bindings.assert_called_once_with(expected)
        artists_view.set_hotkey_bindings.assert_called_once_with(expected)
        window._apply_global_shortcuts.assert_called_once()
        window._register_hotkey_hints.assert_called_once()
        registered_bindings = window._register_hotkey_hints.call_args.args[0]
        self.assertEqual(registered_bindings["snap"], expected["snap"])
        self.assertEqual(registered_bindings["shift_selected"], expected["shift_selected"])
        self.assertEqual(registered_bindings["shift_all_from_first"], expected["shift_all_from_first"])
        window.hotkey_hints.refresh_positions.assert_called_once_with()


@unittest.skipUnless(HAS_QT, "PySide6 is required for widget tests")
class SettingsDialogHotkeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_app()

    def test_settings_dialog_loads_and_saves_custom_hotkeys(self):
        with TemporaryDirectory() as tmp:
            app_state = simple_app_state(initialize_database(tmp))
            try:
                dialog = MusicFoldersDialog(app_state)
                dialog.shortcut_enabled_checks["play_pause"].setChecked(False)
                dialog.shortcut_edits["snap"].setKeySequence(QKeySequence("Tab"))
                dialog.shortcut_edits["shift_selected"].setKeySequence(QKeySequence("Alt+S"))
                dialog.shortcut_edits["shift_all_from_first"].setKeySequence(QKeySequence("Ctrl+Alt+A"))

                dialog.save()

                reloaded = MusicFoldersDialog(app_state)
                try:
                    self.assertFalse(reloaded.shortcut_enabled_checks["play_pause"].isChecked())
                    self.assertEqual(reloaded.shortcut_edits["snap"].keySequence().toString(), "Tab")
                    self.assertEqual(reloaded.shortcut_edits["shift_selected"].keySequence().toString(), "Alt+S")
                    self.assertEqual(reloaded.shortcut_edits["shift_all_from_first"].keySequence().toString(), "Ctrl+Alt+A")
                finally:
                    reloaded.deleteLater()
                    dialog.deleteLater()
            finally:
                app_state.db.close()


@unittest.skipUnless(HAS_QT, "PySide6 is required for widget tests")
class NavigationControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_app()

    def test_tab_switch_restores_last_album_route(self):
        class FakeSignal:
            def __init__(self):
                self._callbacks = []

            def connect(self, callback):
                self._callbacks.append(callback)

            def emit(self, *args):
                for callback in list(self._callbacks):
                    callback(*args)

        class FakeTabs:
            def __init__(self, widgets):
                self.currentChanged = FakeSignal()
                self._widgets = list(widgets)
                self._current = self._widgets[0]

            def widget(self, idx):
                return self._widgets[idx]

            def setCurrentWidget(self, widget):
                self._current = widget
                self.currentChanged.emit(self._widgets.index(widget))

        class FakeLayout:
            def count(self):
                return 0

            def takeAt(self, _index):
                return None

            def addWidget(self, _widget):
                return None

            def addStretch(self, _stretch):
                return None

        tracks_tab = QWidget()
        albums_page = QWidget()
        artists_page = QWidget()
        tabs = FakeTabs([tracks_tab, albums_page, artists_page])
        apply_route = MagicMock()
        controller = NavigationController(
            db=object(),
            tabs=tabs,
            tracks_tab=tracks_tab,
            albums_page=albums_page,
            artists_page=artists_page,
            breadcrumbs_layout=FakeLayout(),
            apply_route=apply_route,
            display_artist_name=lambda value: value or "",
            display_album_name=lambda value: value or "",
        )
        controller._persist_library_route = MagicMock()
        controller._update_breadcrumbs = MagicMock()

        album_route = albums_detail((11,), label="Kid A")
        controller.navigate_to(album_route)
        apply_route.reset_mock()

        tabs.setCurrentWidget(tracks_tab)
        self.assertEqual(controller.current_route, tracks_all())

        tabs.setCurrentWidget(albums_page)

        self.assertEqual(controller.current_route, album_route)
        self.assertEqual(apply_route.call_args_list, [call(tracks_all()), call(album_route)])
