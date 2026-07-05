from __future__ import annotations

import unittest

from core.tracklist_models import LyricsState
from ui.widgets.track_list_rows import build_track_list_rows


class TrackListRowsTests(unittest.TestCase):
    def test_build_track_list_rows_accepts_lightweight_summary_columns(self):
        rows = [
            {
                "id": 1,
                "title": "Song",
                "artist_name": "Artist",
                "artist_id": 10,
                "album_name": "Album",
                "album_id": 20,
                "track_number": 3,
                "duration": 181.4,
                "instrumental": 0,
                "has_lrc_lyrics": 1,
                "has_txt_lyrics": 0,
                "has_instrumental_marker": 0,
                "dirty_txt_lyrics": None,
                "dirty_lrc_lyrics": None,
                "dirty_lyrics_present": 0,
            }
        ]

        ui_rows = build_track_list_rows(rows, {})

        self.assertEqual(len(ui_rows), 1)
        self.assertEqual(ui_rows[0].lyrics_state, LyricsState.SYNCED)
        self.assertEqual(ui_rows[0].track_id, 1)
        self.assertEqual(ui_rows[0].duration_s, 181)


if __name__ == "__main__":
    unittest.main()
