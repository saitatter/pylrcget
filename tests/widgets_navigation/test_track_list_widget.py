from tests.widgets_navigation._shared import *

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
