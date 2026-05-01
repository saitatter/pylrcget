from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PySide6.QtWidgets import QHeaderView

from ui.library_routes import albums_detail, artists_detail, tracks_album, tracks_artist
from ui.controllers.top_bar_controller import TopBarController
from ui.widgets.lrclib_browser_widget import _BrowserPublishDialog
from ui.widgets.lyrics_editor_widget import LyricsEditorWidget
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
