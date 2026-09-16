from __future__ import annotations

from tests.widgets_navigation._shared import *


@unittest.skipUnless(HAS_QT, "PySide6 is required for widget tests")
class BatchLyricsMatchDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_app()

    def test_bulk_match_dialog_shows_provider_source_separately(self):
        from ui.dialogs.batch_lyrics_match_dialog import BatchLyricsMatchDialog
        from ui.services.lyrics_match_retry import LyricsMatchCandidate

        candidate = LyricsMatchCandidate(
            track_id=1,
            track_label="Artist - Song",
            query_label="artist + title",
            score=91,
            artist_name="Artist",
            track_name="Song",
            album_name="Album",
            duration=180,
            kind="Synced",
            plain_lyrics="plain",
            synced_lyrics="[00:01.00]synced",
            provider="tidal",
        )
        dialog = BatchLyricsMatchDialog([candidate])
        try:
            headers = [dialog.table.horizontalHeaderItem(index).text() for index in range(dialog.table.columnCount())]
            assert headers[-2:] == ["Source", "Found by"]
            assert dialog.table.item(0, 6).text() == "TIDAL"
            assert dialog.table.item(0, 7).text() == "artist + title"
        finally:
            dialog.deleteLater()
