from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_support import make_fs_track, touch_text
from db.database import add_tracks, get_album_rows, initialize_database
from db.queries import find_artist


class ArtistAlbumQueryTests(unittest.TestCase):
    def test_get_album_rows_filters_by_track_artist_not_album_artist_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio_a = Path(tmp) / "artist_a.mp3"
                audio_b = Path(tmp) / "artist_b.mp3"
                touch_text(audio_a, "a")
                touch_text(audio_b, "b")

                add_tracks(
                    db,
                    [
                        make_fs_track(audio_a, artist="Artist A", album="Album Shared", title="Song A"),
                        make_fs_track(audio_b, artist="Artist B", album="Album Other", title="Song B"),
                    ],
                )

                artist_a_id = find_artist(db, "Artist A")
                rows = get_album_rows(db, artist_id=artist_a_id)
                album_names = [row["album_name"] for row in rows]
                self.assertEqual(album_names, ["Album Shared"])
            finally:
                db.close()

    def test_get_album_rows_prefers_album_artist_name_for_artist_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "album_artist.mp3"
                touch_text(audio, "a")
                add_tracks(
                    db,
                    [make_fs_track(audio, artist="Track Artist", album="Known Album", title="Song A")],
                )

                rows = get_album_rows(db)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["artist_name"], "Track Artist")
            finally:
                db.close()

    def test_get_album_rows_supports_limit_offset_and_sorting(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                tracks = [
                    ("c.mp3", "Artist C", "Gamma", "Song 1"),
                    ("a.mp3", "Artist A", "Alpha", "Song 2"),
                    ("b.mp3", "Artist B", "Beta", "Song 3"),
                ]
                fs_tracks = []
                for filename, artist, album, title in tracks:
                    path = Path(tmp) / filename
                    touch_text(path, filename)
                    fs_tracks.append(make_fs_track(path, artist=artist, album=album, title=title))
                add_tracks(db, fs_tracks)

                rows = get_album_rows(db, limit=2, offset=1, sort_column=0, sort_order="asc")
                self.assertEqual([row["album_name"] for row in rows], ["Beta", "Gamma"])
            finally:
                db.close()
