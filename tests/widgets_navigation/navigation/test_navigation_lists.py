from tests.widgets_navigation._shared import *


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
            self.assertEqual(list(bucket_ids), [1, 2])
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
            self.assertEqual(list(bucket_ids), [1, 2])
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